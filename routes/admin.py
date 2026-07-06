from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import login_required, current_user
from models import db, Question, Student, Session, WeakTopic, Subject, Response, PasswordResetRequest
from openai import OpenAI
from timezone_utils import format_time_short, format_date_only
from collections import defaultdict
from datetime import datetime
import os
import json
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

admin_bp = Blueprint('admin', __name__)


# ─────────────────────────────────────────
# Make the count of pending password-recovery issues available to
# every admin template (for the sidebar "Issues" badge).
# ─────────────────────────────────────────
@admin_bp.app_context_processor
def inject_sidebar_globals():
    try:
        count = PasswordResetRequest.query.filter_by(status='pending').count()
    except Exception:
        count = 0
    try:
        subjects = Subject.query.order_by(Subject.name).all()
    except Exception:
        subjects = []
    return {'pending_issue_count': count, 'sidebar_subjects': subjects}

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ.get("NVIDIA_API_KEY", "")
)

# Global progress tracking for generation
generation_progress = {
    'current_subject_id': None,
    'current_batch': 0,
    'total_batches': 30,
    'current_questions': 0,
    'total_questions': 1500,
    'status': 'idle',  # idle, generating, complete, error
    'error_message': None
}

_progress_lock = threading.Lock()
MAX_GEN_WORKERS = 6
GENERATION_MODELS = {
    'fast': 'meta/llama-3.1-8b-instruct',
    'quality': 'nvidia/nemotron-3-ultra-550b-a55b',
}


# ─────────────────────────────────────────
# HELPER: Parse AI JSON response with fallback fixes
# ─────────────────────────────────────────
def parse_ai_json_response(raw_response):
    """
    Try to parse AI JSON response with multiple fallback strategies
    Handles common issues like unescaped quotes, newlines, etc.
    """
    # Step 1: Basic cleanup
    cleaned = raw_response.replace('```json', '').replace('```', '').strip()
    
    # Step 2: Find JSON boundaries
    if not cleaned.startswith('['):
        json_start = cleaned.find('[')
        if json_start != -1:
            cleaned = cleaned[json_start:]
        else:
            raise ValueError("No valid JSON array found in response")
    
    if not cleaned.endswith(']'):
        json_end = cleaned.rfind(']')
        if json_end != -1:
            cleaned = cleaned[:json_end + 1]
    
    # Step 3: First attempt - direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Step 4: Try fixing common issues
    # Fix: Unescaped newlines within strings (replace literal newlines with \n)
    lines = cleaned.split('\n')
    fixed = []
    in_string = False
    for line in lines:
        # Simple heuristic: if line doesn't end with comma or bracket, it might be continuation
        if in_string and line.strip() and not line.strip().startswith('}'):
            # This looks like a continuation - add a space instead of newline
            fixed.append(' ' + line)
        else:
            fixed.append(line)
            # Track if we're in a string
            in_string = line.count('"') % 2 == 1
    
    cleaned = '\n'.join(fixed)
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Step 5: Last resort - try to extract objects manually
    # This is more lenient and can handle some malformed JSON
    try:
        # Find all {...} objects
        objects = []
        brace_count = 0
        start = -1
        
        for i, char in enumerate(cleaned):
            if char == '{':
                if brace_count == 0:
                    start = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start != -1:
                    obj_str = cleaned[start:i+1]
                    try:
                        objects.append(json.loads(obj_str))
                    except:
                        pass
                    start = -1
        
        if objects:
            return objects
    except:
        pass
    
    # If we get here, raise with helpful error
    raise ValueError("Could not parse JSON even after attempting fixes. Please simplify the syllabus text.")


# ─────────────────────────────────────────
# HELPER: Generate 1000 fallback questions from syllabus
# Used if AI fails but we still want students to have practice questions
# ─────────────────────────────────────────
def generate_fallback_questions(subject_id, syllabus_text):
    """
    Generate 500 fallback questions from syllabus topics if AI fails
    This ensures students always have a good variety to practice with
    Target: 500 questions total spread across topics and difficulties
    """
    # Extract topics from syllabus (split by newlines and filter)
    lines = [line.strip() for line in syllabus_text.split('\n') if line.strip()]
    
    # Find topic-like lines (short, 8-120 chars, not full sentences typically)
    topics = []
    for line in lines:
        # Skip very short or lines that look like full sentences
        if 8 < len(line) < 120:
            if not line.endswith(':'):  # Remove section markers
                topics.append(line)
    
    # If we found topics, create questions from them
    questions_created = 0
    target_questions = 500
    
    if topics:
        # Determine how many questions per topic
        num_topics_to_use = max(5, min(15, len(topics)))  # Use 5-15 topics
        questions_per_topic = target_questions // num_topics_to_use
        
        for topic_idx in range(num_topics_to_use):
            topic = topics[topic_idx]
            topic_clean = topic.replace(':', '').strip()[:50]
            topic_short = topic_clean[:30]
            
            # Create multiple questions per topic with varying difficulties and question types
            for q_num in range(questions_per_topic):
                # Rotate difficulty: first half easy, second half hard
                difficulty = 'easy' if (q_num % 2 == 0) else 'hard'
                
                # Vary question styles
                question_type = q_num % 5
                
                if question_type == 0:
                    question_text = f'Which of the following best describes {topic_short}?'
                elif question_type == 1:
                    question_text = f'What is the primary purpose of {topic_short}?'
                elif question_type == 2:
                    question_text = f'In the context of {topic_short}, which statement is most accurate?'
                elif question_type == 3:
                    question_text = f'How does {topic_short} relate to the overall subject?'
                else:
                    question_text = f'Which of these scenarios best illustrates {topic_short}?'
                
                # Rotate correct answer through A/B/C/D so no single slot is always right
                correct_slot = q_num % 4

                if difficulty == 'easy':
                    correct_text = f'A key aspect of {topic_short}'
                    distractors = [
                        'Not directly related to the subject',
                        'An outdated concept',
                        'Beyond the scope of this course'
                    ]
                else:
                    correct_text = 'Has practical implications and real-world applications'
                    distractors = [
                        'Only applicable in theoretical contexts',
                        'Primarily relevant for historical understanding',
                        'Varies depending on implementation context'
                    ]

                options = distractors[:]
                options.insert(correct_slot, correct_text)
                correct = chr(ord('A') + correct_slot)

                q = Question(
                    subject_id=subject_id,
                    topic=topic_clean,
                    difficulty=difficulty,
                    question_text=question_text,
                    option_a=options[0],
                    option_b=options[1],
                    option_c=options[2],
                    option_d=options[3],
                    correct_option=correct
                )
                db.session.add(q)
                questions_created += 1
                
                # Batch commit every 250 questions to avoid memory issues
                if questions_created % 250 == 0:
                    try:
                        db.session.commit()
                        print(f"[Fallback] Created {questions_created} questions so far...")
                    except Exception as e:
                        db.session.rollback()
                        print(f"Fallback batch commit error: {e}")
                        return questions_created
                
                # Safety check - stop if we've created exactly 1000
                if questions_created >= target_questions:
                    break
            
            # Safety check - stop if we've created exactly 1000
            if questions_created >= target_questions:
                break
        
        # Final commit for remaining questions
        try:
            db.session.commit()
            print(f"[Fallback] Successfully created {questions_created} fallback questions")
            return questions_created
        except Exception as e:
            db.session.rollback()
            print(f"Fallback final commit error: {e}")
            return questions_created
    
    return 0


# ─────────────────────────────────────────
# HELPER: Generate 1000 questions in batches from AI
# Splits generation into 20 batches of 50 questions each
# ─────────────────────────────────────────
def generate_questions_in_batches(subject, syllabus_text, mode='fast'):
    """
    Generate 500 questions with ALL batches running CONCURRENTLY and STREAMED.
    Worker threads only call the API; DB inserts happen on this (main) thread,
    one batch at a time as each request returns (SQLAlchemy is not thread-safe).
    mode: 'fast' (Llama 3.1 8B) or 'quality' (Nemotron 3 Ultra).
    Returns tuple: (total_questions_created, error_message_or_none)
    """
    global generation_progress

    # Capture ORM values as plain locals BEFORE spawning worker threads. Worker
    # threads have no Flask app context, and each db.session.commit() expires the
    # subject — so touching subject.name/.id from a thread would re-load it and
    # raise "Working outside of application context" (the bug that capped yield).
    subject_id = subject.id
    subject_name = subject.name

    total_questions = 0            # NEW unique questions actually added this run
    questions_per_batch = 50
    TARGET_NEW = 1000              # keep generating until we've ADDED this many unique questions
    MAX_BATCHES = 60              # hard safety cap on attempts (= up to 3000) to bound time/cost
    DRY_STREAK_LIMIT = 3          # give up early if this many waves in a row add ~nothing
    num_batches = MAX_BATCHES     # used in the prompt text ("BATCH x OF y")
    model_id = GENERATION_MODELS.get(mode, GENERATION_MODELS['fast'])

    with _progress_lock:
        generation_progress['status'] = 'generating'
        generation_progress['current_subject_id'] = subject_id
        generation_progress['current_batch'] = 0
        generation_progress['total_batches'] = MAX_BATCHES
        generation_progress['current_questions'] = 0
        generation_progress['total_questions'] = TARGET_NEW
        generation_progress['error_message'] = None

    print(f"\n[BATCH GEN] Target {TARGET_NEW} NEW questions (≤{MAX_BATCHES} batches × {questions_per_batch}, workers={MAX_GEN_WORKERS}, model={model_id})...")

    _topics = [ln.strip(' -•\t') for ln in syllabus_text.split('\n') if len(ln.strip()) > 8] or [subject_name]
    _ANGLES = ['definitions and core terminology', 'real-world application and use-case scenarios',
               'comparison and contrast between related concepts', 'problem-solving and troubleshooting',
               'cause-and-effect / consequence reasoning', 'trade-offs, pros and cons',
               'how it works internally / step-by-step', 'common misconceptions and edge cases']

    def _build_prompt(batch_num):
        _angle = _ANGLES[(batch_num - 1) % len(_ANGLES)]
        _n = len(_topics)
        _start = ((batch_num - 1) * 2) % _n
        _focus = "; ".join(_topics[(_start + k) % _n][:60] for k in range(min(3, _n)))
        return f"""You are a question generator for a student quiz system.

Subject: {subject_name}
Syllabus:
{syllabus_text}

BATCH {batch_num} OF {num_batches}: Generate questions {(batch_num-1)*questions_per_batch + 1} to {batch_num*questions_per_batch}

IMPORTANT INSTRUCTIONS:
1. Generate EXACTLY {questions_per_batch} multiple choice questions for this batch
2. Distribute questions evenly across ALL topics in the syllabus
3. Vary difficulty: alternate between easy and hard to avoid consecutive same difficulty
4. Mix question types: definition, application, analysis, scenario-based, comparison, evaluation
5. Topic names MUST be SHORT - maximum 50 characters
6. **CRITICAL FOR UNIQUENESS - MUST FOLLOW:**
   a) NEVER repeat ANY question text from other batches - all {num_batches*questions_per_batch} questions must be UNIQUE
   b) Create completely different questions for each batch - vary question structure, wording, scenarios
   c) Use different contexts and real-world examples for each variation of a topic
   d) Make distractors (wrong answers) UNIQUE per question - never reuse option combinations
   e) For duplicate-prone topics, ask from different angles (definition vs. application vs. scenario)
   f) When covering the same concept, ask about different aspects or use different examples
7. **CRITICAL FOR VARIED PHRASING - MUST FOLLOW:**
   a) NEVER use repetitive question starters like "What is the primary...", "What is the...", "Which of these..."
   b) Vary question structures significantly:
      - Use different openings: "How", "Why", "In what scenario", "Which statement", "Evaluate", "Compare", "Analyze"
      - Ask about consequences: "What would happen if..."
      - Ask about relationships: "How does X relate to Y?"
      - Ask about distinctions: "What distinguishes X from Y?"
      - Ask about applications: "In which scenario would X be used?"
      - Ask about problems/solutions: "Which approach best solves X?"
   c) Mix question perspectives: ask from user perspective, system perspective, implementation perspective
   d) Ensure NO question text starts with the same phrase - MAXIMUM 1 question per opening pattern
8. Return ONLY valid JSON. No markdown, no extra text.
8. Ensure all strings are properly JSON-escaped
9. Each question must have exactly 4 unique options (A, B, C, D)
10. NO question text should end with the same phrasing as any other question

REQUIRED JSON FORMAT (MUST follow this exactly):
[
  {{
    "topic": "Topic Name",
    "question_text": "What is the question being asked? Be specific and clear.",
    "difficulty": "easy",
    "option_a": "First option text",
    "option_b": "Second option text",
    "option_c": "Third option text",
    "option_d": "Fourth option text",
    "correct_option": "A"
  }}
]

EXAMPLES - NOTE THE VARIED QUESTION PATTERNS:
[
  {{
    "topic": "Data Structures",
    "question_text": "Which data structure provides LIFO (Last In First Out) access?",
    "difficulty": "easy",
    "option_a": "Stack",
    "option_b": "Queue",
    "option_c": "Array",
    "option_d": "Tree",
    "correct_option": "A"
  }},
  {{
    "topic": "Algorithms",
    "question_text": "How does binary search reduce search time compared to linear search?",
    "difficulty": "hard",
    "option_a": "Uses a hash table for faster lookups",
    "option_b": "Eliminates half of the remaining elements with each comparison",
    "option_c": "Stores frequently accessed items in cache memory",
    "option_d": "Parallelizes search operations across multiple cores",
    "correct_option": "B"
  }},
  {{
    "topic": "Data Structures",
    "question_text": "In what scenario would you choose a linked list over an array?",
    "difficulty": "hard",
    "option_a": "When you need random access to elements",
    "option_b": "When frequent insertions/deletions occur at non-endpoints",
    "option_c": "When memory is abundant and speed is not critical",
    "option_d": "When sorting data regularly",
    "correct_option": "B"
  }},
  {{
    "topic": "Algorithms",
    "question_text": "What distinguishes quicksort from mergesort in terms of space complexity?",
    "difficulty": "hard",
    "option_a": "Quicksort uses less auxiliary space",
    "option_b": "Mergesort uses less auxiliary space",
    "option_c": "They use identical amounts of auxiliary space",
    "option_d": "Space complexity depends only on input size",
    "correct_option": "A"
  }}
]""" + (
            f"\n\nBATCH FOCUS (batch {batch_num} of {num_batches}) — this keeps questions UNIQUE across batches:\n"
            f"- Emphasize this question angle for THIS batch: {_angle}.\n"
            f"- Lean toward these syllabus areas this batch: {_focus}.\n"
            f"- Deliberately avoid generic phrasings or scenarios that other batches would also produce.\n")

    def _stream_batch(batch_num):
        """Worker thread: stream the API call, update streamed-question progress,
        return the raw text. NO database access here."""
        prompt = _build_prompt(batch_num)
        last_err = None
        for attempt in range(3):
            try:
                text = ''
                counted = 0
                stream = client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.85,
                    top_p=0.95,
                    max_tokens=4096,
                    stream=True,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if not delta:
                        continue
                    text += delta
                    counted = text.count('"correct_option"')
                print(f"[BATCH {batch_num}/{num_batches}] streamed {counted} questions")
                return text
            except Exception as e:
                last_err = e
                print(f"[BATCH {batch_num}/{num_batches}] retry {attempt + 1}/3 after error: {e}")
                time.sleep(1.5 * (attempt + 1))
        raise last_err

    def _insert_batch(raw, batch_num):
        """Main thread only: parse raw JSON and insert questions into the DB."""
        questions_data = parse_ai_json_response(raw)
        batch_count = 0
        skipped_count = 0
        duplicate_count = 0
        for q in questions_data:
            option_a = str(q.get('option_a', '')).strip()
            option_b = str(q.get('option_b', '')).strip()
            option_c = str(q.get('option_c', '')).strip()
            option_d = str(q.get('option_d', '')).strip()
            question_text = str(q.get('question_text', '')).strip()
            topic = str(q.get('topic', '')).strip()[:100]
            if not all([option_a, option_b, option_c, option_d, question_text, topic]):
                skipped_count += 1
                continue
            existing = Question.query.filter_by(
                subject_id=subject_id,
                question_text=question_text
            ).first()
            if existing:
                duplicate_count += 1
                continue
            difficulty = str(q.get('difficulty', 'easy')).lower()
            if difficulty not in ['easy', 'hard']:
                difficulty = 'easy'
            correct = str(q.get('correct_option', 'A')).upper()
            if correct not in ['A', 'B', 'C', 'D']:
                correct = 'A'
            db.session.add(Question(
                subject_id=subject_id,
                topic=topic,
                difficulty=difficulty,
                question_text=question_text,
                option_a=option_a,
                option_b=option_b,
                option_c=option_c,
                option_d=option_d,
                correct_option=correct
            ))
            batch_count += 1
        db.session.commit()
        print(f"[BATCH {batch_num}/{num_batches}] created {batch_count} (skipped {skipped_count}, dupes {duplicate_count})")
        return batch_count

    # Keep launching parallel waves of batches until we've ADDED enough unique
    # questions, hit the batch cap, or the syllabus is exhausted (dry streak).
    batch_no = 0
    dry_streak = 0
    with ThreadPoolExecutor(max_workers=MAX_GEN_WORKERS) as ex:
        while total_questions < TARGET_NEW and batch_no < MAX_BATCHES and dry_streak < DRY_STREAK_LIMIT:
            wave = {}
            for _ in range(MAX_GEN_WORKERS):
                if batch_no >= MAX_BATCHES:
                    break
                batch_no += 1
                wave[ex.submit(_stream_batch, batch_no)] = batch_no
            wave_added = 0
            for fut in as_completed(wave):
                b = wave[fut]
                try:
                    raw = fut.result()
                except Exception as e:
                    print(f"[BATCH {b}] API error after retries: {e}")
                    continue
                try:
                    added = _insert_batch(raw, b)
                    total_questions += added
                    wave_added += added
                except (json.JSONDecodeError, ValueError) as je:
                    print(f"[BATCH {b}] JSON parsing error: {je}")
                    db.session.rollback()
                except Exception as e:
                    print(f"[BATCH {b}] DB error: {e}")
                    db.session.rollback()
                with _progress_lock:
                    generation_progress['current_batch'] = batch_no
                    generation_progress['current_questions'] = min(total_questions, TARGET_NEW)
            # A whole wave that adds almost nothing means the model has run out of
            # genuinely new questions for this syllabus — stop wasting API calls.
            dry_streak = dry_streak + 1 if wave_added < 10 else 0
            print(f"[BATCH GEN] wave added +{wave_added} (new total {total_questions}/{TARGET_NEW}, batches used {batch_no}, dry={dry_streak})")

    if total_questions > 0:
        generation_progress['status'] = 'complete'
    else:
        generation_progress['status'] = 'error'
        generation_progress['error_message'] = 'Failed to generate questions'
    generation_progress['current_questions'] = total_questions

    print(f"\n[BATCH GEN] Done. Added {total_questions} new questions (target {TARGET_NEW}, batches used {batch_no}).\n")
    return total_questions, None if total_questions > 0 else "Failed to generate sufficient questions"


def _run_generation(app, subject_id, syllabus_text):
    """Run question generation in a BACKGROUND thread so the HTTP request returns
    immediately. Progress is tracked via the global generation_progress dict, which
    the UI polls at /admin/api/generation-progress."""
    with app.app_context():
        try:
            subject = Subject.query.get(subject_id)
            if not subject:
                generation_progress['status'] = 'error'
                generation_progress['error_message'] = 'Subject not found'
                return

            total_count, _err = generate_questions_in_batches(subject, syllabus_text)

            if total_count >= 50:
                subject.syllabus_text = syllabus_text
                db.session.commit()
                generation_progress['status'] = 'complete'
                generation_progress['current_subject_id'] = int(subject_id)
                print(f"[UPLOAD] Generated {total_count} questions for '{subject.name}'.")
                return

            # AI produced too few — fall back to syllabus-derived questions
            db.session.rollback()
            print(f"[UPLOAD] Only {total_count} from AI — running fallback...")
            fallback_count = generate_fallback_questions(subject_id, syllabus_text)
            subject = Subject.query.get(subject_id)
            if fallback_count > 0:
                subject.syllabus_text = syllabus_text
                db.session.commit()
                generation_progress['status'] = 'complete'
                generation_progress['current_subject_id'] = int(subject_id)
            else:
                generation_progress['status'] = 'error'
                generation_progress['error_message'] = 'Could not generate questions.'
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            generation_progress['status'] = 'error'
            generation_progress['error_message'] = str(e)
            print(f"[UPLOAD] Background generation error: {e}")


# ─────────────────────────────────────────
# HELPER: Check if subject has questions
# ─────────────────────────────────────────
def subject_has_questions(subject_id):
    """Check if a subject has any questions"""
    return Question.query.filter_by(subject_id=subject_id).count() > 0


# ─────────────────────────────────────────
# GENERATION PROGRESS TRACKING (for floating button)
# ─────────────────────────────────────────
@admin_bp.route('/api/generation-progress')
@login_required
def get_generation_progress():
    """Return current generation progress for floating button"""
    global generation_progress
    
    return jsonify({
        'status': generation_progress['status'],
        'current_subject_id': generation_progress['current_subject_id'],
        'current_batch': generation_progress['current_batch'],
        'total_batches': generation_progress['total_batches'],
        'current_questions': generation_progress['current_questions'],
        'total_questions': generation_progress['total_questions'],
        'progress_percent': (generation_progress['current_questions'] / generation_progress['total_questions'] * 100) if generation_progress['total_questions'] > 0 else 0,
        'error_message': generation_progress['error_message']
    })


# ─────────────────────────────────────────
# STUDENTS — alphabetical list with search
# ─────────────────────────────────────────
@admin_bp.route('/students')
@login_required
def view_students():
    students = Student.query.order_by(Student.name).all()
    student_data = []
    for s in students:
        session_count = Session.query.filter_by(student_id=s.id).count()
        completed_count = Session.query.filter_by(student_id=s.id, status='completed').count()
        student_data.append({
            'student': s,
            'session_count': session_count,
            'completed_count': completed_count,
        })
    return render_template('students_admin.html', student_data=student_data)


# ─────────────────────────────────────────
# ISSUES — password-recovery requests raised by students
# Clicking an issue jumps to the Students section focused on that student.
# ─────────────────────────────────────────
@admin_bp.route('/issues')
@login_required
def view_issues():
    # Pending first, then most recent first
    requests = PasswordResetRequest.query.order_by(
        PasswordResetRequest.status.asc(),
        PasswordResetRequest.created_at.desc()
    ).all()

    issues = []
    for r in requests:
        student = Student.query.get(r.student_id) if r.student_id else None
        # Fall back to matching by email for legacy/unlinked rows
        if not student:
            student = Student.query.filter_by(email=r.email).first()
        issues.append({
            'id': r.id,
            'email': r.email,
            'name': (student.name if student else None) or r.name,
            'student_id': student.id if student else None,
            'has_account': student is not None,
            'status': r.status,
            'created_at': r.created_at,
            'resolved_at': r.resolved_at,
        })

    pending_count = sum(1 for i in issues if i['status'] == 'pending')
    return render_template('issues_admin.html', issues=issues, pending_count=pending_count)


@admin_bp.route('/issues/<int:request_id>/resolve', methods=['POST'])
@login_required
def resolve_issue(request_id):
    req = PasswordResetRequest.query.get(request_id)
    if not req:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        flash('Issue not found.', 'danger')
        return redirect(url_for('admin.view_issues'))

    req.status = 'resolved'
    req.resolved_at = datetime.utcnow()
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    flash('Issue marked as resolved.', 'success')
    return redirect(url_for('admin.view_issues'))


# ─────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    all_subjects = Subject.query.all()
    total_students = Student.query.count()
    total_sessions = Session.query.count()
    completed_sessions = Session.query.filter(Session.status == 'completed').count()
    total_questions = Question.query.count()
    total_subjects = len(all_subjects)
    return render_template('dashboard.html',
                           total_students=total_students,
                           total_sessions=total_sessions,
                           completed_sessions=completed_sessions,
                           total_questions=total_questions,
                           total_subjects=total_subjects,
                           subjects=all_subjects)


# ─────────────────────────────────────────
# SUBJECTS LIST
# ─────────────────────────────────────────
@admin_bp.route('/subjects', methods=['GET'])
@login_required
def view_subjects():
    all_subjects = Subject.query.all()
    return render_template('subjects.html', subjects=all_subjects)


# ─────────────────────────────────────────
# CREATE SUBJECT
# On success → redirect to /admin/subjects (styled dark page)
# Never redirect to create_subject after success — avoids flash bleed
# ─────────────────────────────────────────
@admin_bp.route('/subject/create', methods=['GET', 'POST'])
@login_required
def create_subject():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            flash('Subject name is required.', 'danger')
            return redirect(url_for('admin.create_subject'))

        # Check for duplicates
        existing = Subject.query.filter_by(name=name).first()
        if existing:
            flash(f'A subject named "{name}" already exists.', 'danger')
            return redirect(url_for('admin.create_subject'))

        try:
            subject = Subject(
                name=name,
                description=description if description else None,
                admin_id=current_user.id
            )
            db.session.add(subject)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash('Failed to create subject due to a server error. Please try again.', 'danger')
            return redirect(url_for('admin.create_subject'))

        # Flash success and redirect to subjects list (dark-themed page)
        flash(f'Subject "{name}" created successfully!', 'success')
        return redirect(url_for('admin.view_subjects'))

    return render_template('create_subject.html')


# ─────────────────────────────────────────
# DELETE SUBJECT
# ─────────────────────────────────────────
@admin_bp.route('/subject/<int:subject_id>/delete', methods=['POST'])
@login_required
def delete_subject(subject_id):
    subject = Subject.query.get(subject_id)
    if not subject:
        flash('Subject not found.', 'danger')
        return redirect(url_for('admin.view_subjects'))
    name = subject.name
    try:
        db.session.delete(subject)
        db.session.commit()
        flash(f'Subject "{name}" deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Failed to delete subject.', 'danger')
    return redirect(url_for('admin.view_subjects'))


# ─────────────────────────────────────────
# EDIT SUBJECT (name + description)
# ─────────────────────────────────────────
@admin_bp.route('/subject/<int:subject_id>/edit', methods=['POST'])
@login_required
def edit_subject(subject_id):
    subject = Subject.query.get(subject_id)
    if not subject:
        flash('Subject not found.', 'danger')
        return redirect(url_for('admin.view_subjects'))

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    if not name:
        flash('Subject name is required.', 'danger')
        return redirect(url_for('admin.view_subjects'))

    # Prevent renaming onto another subject's name
    dupe = Subject.query.filter(Subject.name == name, Subject.id != subject_id).first()
    if dupe:
        flash(f'Another subject named "{name}" already exists.', 'danger')
        return redirect(url_for('admin.view_subjects'))

    try:
        subject.name = name
        subject.description = description if description else None
        db.session.commit()
        flash(f'Subject updated to "{name}".', 'success')
    except Exception:
        db.session.rollback()
        flash('Failed to update subject.', 'danger')
    return redirect(url_for('admin.view_subjects'))


# ─────────────────────────────────────────
# UPLOAD SYLLABUS & GENERATE 1000 QUESTIONS
# Flash messages here are question-generation specific
# They only appear on the upload page
# ─────────────────────────────────────────
@admin_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_syllabus():
    all_subjects = Subject.query.all()

    if request.method == 'POST':
        subject_id = request.form.get('subject_id')
        syllabus_text = request.form.get('syllabus_text', '').strip()

        if not subject_id or not syllabus_text:
            error_msg = 'Please select a subject and paste syllabus text.'

            # Check if this is AJAX request
            if request.headers.get('Accept') == 'text/html':
                return jsonify({'success': False, 'message': error_msg})
            else:
                flash(error_msg, 'danger')
                return redirect(url_for('admin.upload_syllabus'))

        # Cap syllabus size to bound the payload sent to the AI API and limit
        # prompt-injection surface. ~50k chars is plenty for any real syllabus.
        MAX_SYLLABUS_CHARS = 50000
        if len(syllabus_text) > MAX_SYLLABUS_CHARS:
            error_msg = f'Syllabus text is too long (max {MAX_SYLLABUS_CHARS:,} characters).'
            if request.headers.get('Accept') == 'text/html':
                return jsonify({'success': False, 'message': error_msg})
            flash(error_msg, 'danger')
            return redirect(url_for('admin.upload_syllabus'))

        subject = Subject.query.get(subject_id)
        if not subject:
            error_msg = 'Selected subject not found.'
            
            # Check if AJAX
            if request.headers.get('Accept') == 'text/html':
                return jsonify({'success': False, 'message': error_msg})
            else:
                flash(error_msg, 'danger')
                return redirect(url_for('admin.upload_syllabus'))

        # Run generation in a BACKGROUND thread so this request returns immediately.
        # The page polls /admin/api/generation-progress and redirects to the questions
        # page when status == 'complete' (avoids multi-minute held requests timing out).
        generation_progress['status'] = 'generating'
        generation_progress['current_subject_id'] = int(subject_id)
        generation_progress['current_batch'] = 0
        generation_progress['current_questions'] = 0
        generation_progress['error_message'] = None
        app = current_app._get_current_object()
        threading.Thread(target=_run_generation, args=(app, subject_id, syllabus_text), daemon=True).start()

        if request.headers.get('Accept') == 'text/html':
            return jsonify({'success': True, 'started': True, 'subject_id': subject_id})
        flash('Question generation started - track progress on this page.', 'success')
        return redirect(url_for('admin.view_questions', subject_id=subject_id))

    selected_subject = None
    subject_id_param = request.args.get('subject_id')
    if subject_id_param:
        selected_subject = Subject.query.get(subject_id_param)

    return render_template('upload_syllabus.html',
                           subjects=all_subjects,
                           selected_subject=selected_subject)


# ─────────────────────────────────────────
# VIEW QUESTIONS
# ─────────────────────────────────────────
@admin_bp.route('/questions')
@login_required
def view_questions():
    subject_id = request.args.get('subject_id')
    all_subjects = Subject.query.all()

    if subject_id:
        subject = Subject.query.get(subject_id)
        if not subject:
            flash('Subject not found.', 'danger')
            return redirect(url_for('admin.dashboard'))
        questions = Question.query.filter_by(subject_id=subject_id).all()
        return render_template('questions.html',
                               questions=questions,
                               subject=subject,
                               all_subjects=all_subjects)
    else:
        all_questions = Question.query.all()
        return render_template('questions.html',
                               questions=all_questions,
                               subject=None,
                               all_subjects=all_subjects)


# ─────────────────────────────────────────
# REPORTS — grouped by student
# ─────────────────────────────────────────
@admin_bp.route('/reports')
@login_required
def reports():
    sessions = Session.query.filter(
        Session.status == 'completed'
    ).order_by(Session.completed_at.desc()).all()

    grouped = defaultdict(lambda: {'name': '', 'subjects': [], 'attempts': []})

    for s in sessions:
        student = Student.query.get(s.student_id)
        subject = Subject.query.get(s.subject_id)
        if not student:
            continue

        email = student.email
        grouped[email]['name'] = student.name

        # ALGORITHM FIX: Determine weak/strong topics based on PERFORMANCE THRESHOLD
        # A topic is "weak" if accuracy < 50%, "strong" if >= 50%
        all_responses = Response.query.filter_by(session_id=s.id).all()
        topic_performance = {}
        
        for response in all_responses:
            resp_question = Question.query.get(response.question_id)
            if resp_question:
                topic = resp_question.topic
                if topic not in topic_performance:
                    topic_performance[topic] = {'correct': 0, 'total': 0}
                
                topic_performance[topic]['total'] += 1
                if response.is_correct:
                    topic_performance[topic]['correct'] += 1
        
        # Identify weak topics (accuracy < 50%)
        weak_names = []
        for topic, perf in topic_performance.items():
            accuracy = (perf['correct'] / perf['total'] * 100) if perf['total'] > 0 else 0
            if accuracy < 50:
                weak_names.append(topic)

        correct_count = Response.query.filter_by(session_id=s.id, is_correct=True).count()
        wrong_count = Response.query.filter_by(session_id=s.id, is_correct=False).count()

        subj_name = subject.name if subject else 'Unknown'
        if subj_name not in grouped[email]['subjects']:
            grouped[email]['subjects'].append(subj_name)

        grouped[email]['attempts'].append({
            'session_id': s.id,
            'subject': subj_name,
            'completed_at': s.completed_at,
            'weak_topics': weak_names,
            'correct_count': correct_count,
            'wrong_count': wrong_count,
        })

    all_subjects = list(set([s.name for s in Subject.query.all()]))
    return render_template('reports.html',
                           grouped_reports=grouped,
                           all_subjects=all_subjects)


# ─────────────────────────────────────────
# MODAL API ROUTES for Dashboard
# ─────────────────────────────────────────
@admin_bp.route('/api/students')
@login_required
def api_students():
    students = Student.query.all()
    result = []
    for s in students:
        session_count = Session.query.filter_by(student_id=s.id).count()
        result.append({
            'id': s.id,
            'name': s.name,
            'email': s.email,
            'session_count': session_count,
            'created_at': format_date_only(s.created_at)
        })
    return jsonify(result)


@admin_bp.route('/api/sessions')
@login_required
def api_sessions():
    sessions = Session.query.order_by(Session.started_at.desc()).limit(50).all()
    result = []
    for s in sessions:
        student = Student.query.get(s.student_id)
        subject = Subject.query.get(s.subject_id)
        result.append({
            'id': s.id,
            'student': student.name if student else 'Unknown',
            'subject': subject.name if subject else 'Unknown',
            'status': s.status,
            'started_at': format_time_short(s.started_at)
        })
    return jsonify(result)


# ─────────────────────────────────────────
# PASSWORD RESET - Admin only feature
# ─────────────────────────────────────────
@admin_bp.route('/api/reset-password', methods=['POST'])
@login_required
def api_reset_password():
    """
    Reset a student's password to a temporary one
    Admin dashboard will display this temp password to the admin
    """
    from extensions import bcrypt
    import secrets

    data = request.get_json(silent=True) or {}
    try:
        student_id = int(data.get('student_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'A valid Student ID is required'}), 400

    student = Student.query.get(student_id)
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    
    # Generate a strong temporary password (12 characters)
    # Format: 6 uppercase + 6 lowercase + 6 digits
    temp_password = (
        secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ') * 2 +
        secrets.choice('abcdefghijklmnopqrstuvwxyz') * 2 +
        ''.join(secrets.choice('0123456789') for _ in range(8))
    )
    # Shuffle it
    temp_password_list = list(temp_password)
    import random as py_random
    py_random.shuffle(temp_password_list)
    temp_password = ''.join(temp_password_list)
    
    # Hash and save
    hashed_pw = bcrypt.generate_password_hash(temp_password).decode('utf-8')
    student.password_hash = hashed_pw
    # Force the student to set their own password at next login
    student.must_change_password = True

    # Auto-resolve any pending password-recovery issues for this student
    pending = PasswordResetRequest.query.filter(
        PasswordResetRequest.status == 'pending',
        db.or_(
            PasswordResetRequest.student_id == student.id,
            PasswordResetRequest.email == student.email
        )
    ).all()
    for req in pending:
        req.status = 'resolved'
        req.resolved_at = datetime.utcnow()

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'Password reset for {student.name}',
        'student_name': student.name,
        'student_email': student.email,
        'temp_password': temp_password  # Send to admin (they see it on screen)
    })


@admin_bp.route('/reset-password', methods=['GET', 'POST'])
@login_required
def reset_password_page():
    """
    Admin page to reset student passwords
    GET: Shows list of students with reset button
    POST: Processes password reset
    """
    if request.method == 'GET':
        students = Student.query.all()
        return render_template('reset_password.html', students=students)
    
    # POST: Just redirect to GET to avoid form resubmission
    return redirect(url_for('admin.reset_password_page'))
