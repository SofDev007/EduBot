from flask import Blueprint, request, jsonify, session as flask_session
from flask_login import current_user
from models import db, Question, Student, Session, Response, WeakTopic, Subject
from datetime import datetime
import random
import json
import sqlalchemy

api_bp = Blueprint('api', __name__)


# ─────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────
def _current_student_id():
    """Return the logged-in student's id from the session, or None."""
    sid = flask_session.get('student_id')
    try:
        return int(sid) if sid is not None else None
    except (TypeError, ValueError):
        return None


def _is_admin():
    """True if an admin is authenticated via flask-login."""
    try:
        return bool(current_user.is_authenticated)
    except Exception:
        return False


def _as_int(value):
    """Coerce a value to int, returning None if it isn't a valid integer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

# ─────────────────────────────────────────
# HELPER: Shuffle queryset using Python random (cross-database compatible)
# ─────────────────────────────────────────
def random_from_query(query):
    """Get random item from SQLAlchemy query results (cross-database compatible)"""
    results = query.all()
    return random.choice(results) if results else None

# ─────────────────────────────────────────
# HELPER: Select random questions from 1000+ question pool
# Uses adaptive logic but selects randomly to ensure variety
# ─────────────────────────────────────────
def select_quiz_questions(subject_id, student_id, num_questions=25, questions_per_topic=5):
    """
    Select questions with MAXIMUM TOPIC COVERAGE.
    Strategy:
    1. Guarantee at least 1 question from EACH topic
    2. Then distribute remaining questions across topics
    3. Ensure NO duplicates within session
    """
    # Get all questions for this subject
    all_questions = Question.query.filter_by(subject_id=subject_id).all()
    
    if not all_questions:
        return []
    
    # Get questions student has already answered (for retake functionality)
    student_answered = db.session.query(Response.question_id).join(
        Session, Response.session_id == Session.id
    ).filter(Session.student_id == student_id).all()
    student_answered_ids = set([r[0] for r in student_answered])
    
    # Get available (unanswered) questions
    available_questions = [q for q in all_questions if q.id not in student_answered_ids]
    
    # If we don't have enough fresh questions, allow repeats but still ensure no duplicates IN THIS QUIZ
    if len(available_questions) < num_questions:
        available_questions = all_questions
    
    # Organize questions by topic
    topics_dict = {}
    for q in available_questions:
        if q.topic not in topics_dict:
            topics_dict[q.topic] = []
        topics_dict[q.topic].append(q)
    
    selected_question_ids = set()
    all_topics = list(topics_dict.keys())
    
    print(f"[API] Available topics: {len(all_topics)}, Total questions: {len(available_questions)}")
    
    # ════════════════════════════════════════════════════════════════════
    # PHASE 1: Guarantee at least 1 question from EACH topic
    # ════════════════════════════════════════════════════════════════════
    for topic in all_topics:
        if len(selected_question_ids) >= num_questions:
            break
        
        questions_in_topic = topics_dict[topic]
        if questions_in_topic:
            selected = random.choice(questions_in_topic)
            selected_question_ids.add(selected.id)
    
    print(f"[API] Phase 1: {len(selected_question_ids)} questions (1 per topic)")
    
    # ════════════════════════════════════════════════════════════════════
    # PHASE 2: Fill remaining slots with balanced distribution
    # ════════════════════════════════════════════════════════════════════
    while len(selected_question_ids) < num_questions:
        # Randomly select a topic
        topic = random.choice(all_topics)
        questions_in_topic = topics_dict[topic]
        
        # Get unselected questions from this topic
        available_in_topic = [q for q in questions_in_topic if q.id not in selected_question_ids]
        
        if available_in_topic:
            selected = random.choice(available_in_topic)
            selected_question_ids.add(selected.id)
        else:
            # If this topic has no more questions, pick from any other available
            all_available = [q for q in available_questions if q.id not in selected_question_ids]
            if all_available:
                selected = random.choice(all_available)
                selected_question_ids.add(selected.id)
            else:
                break
    
    final_ids = list(selected_question_ids)
    topics_covered = set()
    for q_id in final_ids:
        q = next((q for q in available_questions if q.id == q_id), None)
        if q:
            topics_covered.add(q.topic)
    
    print(f"[API] Selected {len(final_ids)} questions from {len(topics_covered)}/{len(all_topics)} topics")
    print(f"[API] Topic coverage: {sorted(topics_covered)}")
    return final_ids


# ─────────────────────────────────────────
# ENDPOINT 0: Get All Subjects
# ─────────────────────────────────────────
@api_bp.route('/subjects', methods=['GET'])
def get_subjects():
    # Only logged-in students or admins may list subjects.
    if _current_student_id() is None and not _is_admin():
        return jsonify({'error': 'Authentication required.'}), 401
    subjects = Subject.query.all()
    return jsonify({
        'status': 'success',
        'subjects': [{
            'id': s.id,
            'name': s.name,
            'description': s.description,
            'question_count': len(s.questions)
        } for s in subjects]
    })


# ─────────────────────────────────────────
# ENDPOINT 1: Start Quiz
# ─────────────────────────────────────────
@api_bp.route('/start', methods=['POST'])
def start_quiz():
    # Require a logged-in student. Identity comes from the session — NOT the
    # request body — so nobody can start a quiz on behalf of another student.
    student_id = _current_student_id()
    if student_id is None:
        return jsonify({'error': 'Please log in to start a quiz.'}), 401

    # Block temp-password users from starting a quiz until they change it
    if flask_session.get('must_change_password'):
        return jsonify({'error': 'Please change your temporary password before starting a quiz.'}), 403
    try:
        data = request.json
        if data is None:
            data = request.form.to_dict()
        if isinstance(data, str):
            data = json.loads(data)
    except:
        data = request.form.to_dict()

    subject_id = _as_int(data.get('subject_id'))
    if subject_id is None:
        return jsonify({'error': 'A valid subject_id is required'}), 400

    subject = Subject.query.get(subject_id)
    if not subject:
        return jsonify({'error': 'Subject not found'}), 404

    student = Student.query.get(student_id)
    if not student:
        # Session points to a student that no longer exists — force re-login.
        flask_session.clear()
        return jsonify({'error': 'Your account was not found. Please log in again.'}), 401

    selected_question_ids = select_quiz_questions(
        subject_id=subject_id, student_id=student.id
    )

    if not selected_question_ids:
        return jsonify({'error': 'No questions available for this subject.'}), 404

    # Validation: Ensure no duplicates in selected questions
    unique_selected = list(set(selected_question_ids))
    if len(unique_selected) != len(selected_question_ids):
        print(f"[START] Warning: Removed {len(selected_question_ids) - len(unique_selected)} duplicate IDs")
        selected_question_ids = unique_selected

    session = Session(student_id=student.id, subject_id=subject_id)
    session.selected_question_ids = json.dumps(selected_question_ids)
    db.session.add(session)
    db.session.commit()
    
    print(f"[START] New session {session.id}: {len(selected_question_ids)} questions selected for student {student.id}")

    first_questions = Question.query.filter(
        Question.id.in_(selected_question_ids),
        Question.difficulty == 'easy'
    ).all()

    if not first_questions:
        first_questions = [Question.query.get(selected_question_ids[0])]

    question = random.choice(first_questions)

    return jsonify({
        'status': 'success',
        'session_id': session.id,
        'student_id': student.id,
        'subject_id': subject_id,
        'subject_name': subject.name,
        'total_questions': len(selected_question_ids),
        'question_number': 1,
        'question': {
            'id': question.id,
            'topic': question.topic,
            'text': question.question_text,
            'options': {
                'A': question.option_a,
                'B': question.option_b,
                'C': question.option_c,
                'D': question.option_d
            }
        }
    })


# ─────────────────────────────────────────
# ENDPOINT 2: Submit Answer
# ─────────────────────────────────────────
@api_bp.route('/answer', methods=['POST'])
def submit_answer():
    try:
        # Require a logged-in student before anything is read or written.
        owner_id = _current_student_id()
        if owner_id is None:
            return jsonify({'error': 'Please log in to submit answers.'}), 401

        data = request.json or {}
        session_id = _as_int(data.get('session_id'))
        question_id = _as_int(data.get('question_id'))
        selected_option = str(data.get('selected_option', data.get('answer', ''))).upper()

        if session_id is None or question_id is None or not selected_option:
            missing = [k for k, v in {'session_id': session_id, 'question_id': question_id, 'selected_option': selected_option}.items() if not v and v != 0]
            return jsonify({'error': f'Missing or invalid fields: {missing}'}), 400

        if selected_option not in ('A', 'B', 'C', 'D'):
            return jsonify({'error': 'selected_option must be one of A, B, C, D.'}), 400

        session = Session.query.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        # ── Ownership check FIRST (before any write) ──────────────────────────
        # The session must belong to the logged-in student. This blocks answering
        # in another student's session by guessing session_ids.
        if session.student_id and int(session.student_id) != owner_id:
            return jsonify({'error': 'This quiz session does not belong to you.'}), 403

        subject_id = session.subject_id
        question = Question.query.get(question_id)
        if not question:
            return jsonify({'error': 'Question not found'}), 404

        # ── Anti-cheat ────────────────────────────────────────────────────────
        # Block console scripts from harvesting the answer key: a question can
        # only be answered if it belongs to THIS session, and only once. This
        # prevents POSTing arbitrary question_ids to read their correct_option.
        session_pool = []
        if session.selected_question_ids:
            try:
                session_pool = json.loads(session.selected_question_ids)
            except Exception:
                session_pool = []
        if session_pool and question.id not in session_pool:
            return jsonify({'error': 'This question is not part of your quiz.'}), 403
        if Response.query.filter_by(session_id=session_id, question_id=question.id).first():
            return jsonify({'error': 'This question has already been answered.'}), 409

        is_correct = (selected_option == question.correct_option)

        response = Response(
            session_id=session_id,
            question_id=question_id,
            selected_option=selected_option,
            is_correct=is_correct
        )
        db.session.add(response)
        db.session.commit()
        
        # NOTE: Weak topic marking is now handled in get_next_question() 
        # when 2 hard questions on same topic are answered incorrectly

        asked_ids = [r.question_id for r in Response.query.filter_by(session_id=session_id).all()]
        
        # Load selected_ids from session FIRST
        selected_ids = []
        if session.selected_question_ids:
            try:
                selected_ids = json.loads(session.selected_question_ids)
            except:
                selected_ids = []
        
        # Log for debugging duplication issues
        print(f"\n[SUBMIT] Session {session_id}: Question {question_id} answered")
        print(f"[SUBMIT] Total questions in session: {len(selected_ids) if selected_ids else 0}")
        print(f"[SUBMIT] Questions already asked: {len(asked_ids)}")
        print(f"[SUBMIT] Asked IDs: {asked_ids}")

        next_question = get_next_question(
            session_id=session_id,
            subject_id=subject_id,
            current_topic=question.topic,
            current_difficulty=question.difficulty,
            is_correct=is_correct,
            asked_ids=asked_ids,
            selected_ids=selected_ids
        )

        if not next_question:
            session.status = 'completed'
            session.completed_at = datetime.utcnow()
            db.session.commit()

            questions_asked = len(asked_ids)
            
            # ALGORITHM FIX: Determine weak/strong topics based on PERFORMANCE THRESHOLD
            # A topic is "weak" if accuracy < 50%, "strong" if >= 50%
            
            all_responses = Response.query.filter_by(session_id=session_id).all()
            topic_performance = {}  # {topic_name: {'correct': X, 'total': Y, 'accuracy': Z%}}
            
            # Calculate accuracy per topic
            for response in all_responses:
                resp_question = Question.query.get(response.question_id)
                if resp_question:
                    topic = resp_question.topic
                    if topic not in topic_performance:
                        topic_performance[topic] = {'correct': 0, 'total': 0}
                    
                    topic_performance[topic]['total'] += 1
                    if response.is_correct:
                        topic_performance[topic]['correct'] += 1
            
            # Calculate accuracy percentage for each topic
            for topic in topic_performance:
                correct = topic_performance[topic]['correct']
                total = topic_performance[topic]['total']
                accuracy = (correct / total * 100) if total > 0 else 0
                topic_performance[topic]['accuracy'] = accuracy
            
            # Classify as weak (< 50% accuracy) or strong (>= 50% accuracy)
            weak_names = []
            strong_names = []
            
            for topic, perf in topic_performance.items():
                if perf['accuracy'] < 50:
                    weak_names.append(topic)
                else:
                    strong_names.append(topic)
            
            print(f"[COMPLETION] Session {session_id}: Topic Performance Analysis:")
            for topic, perf in topic_performance.items():
                print(f"  {topic}: {perf['correct']}/{perf['total']} ({perf['accuracy']:.0f}%) - {'WEAK' if perf['accuracy'] < 50 else 'STRONG'}")

            # Calculate overall score
            correct_count = Response.query.filter_by(session_id=session_id, is_correct=True).count()
            wrong_count = Response.query.filter_by(session_id=session_id, is_correct=False).count()

            return jsonify({
                'status': 'quiz_complete',
                'quiz_complete': True,
                'correct': is_correct,
                'is_correct': is_correct,
                'correct_answer': question.correct_option,
                'total_questions_asked': questions_asked,
                'weak_topics': weak_names,
                'strong_topics': strong_names,
                'total_correct': correct_count,
                'total_wrong': wrong_count,
                'topic_performance': topic_performance  # Include detailed performance data
            })

        questions_asked_so_far = len(asked_ids)

        return jsonify({
            'status': 'next_question',
            'quiz_complete': False,
            'correct': is_correct,
            'is_correct': is_correct,
            'correct_answer': question.correct_option,
            'question_number': questions_asked_so_far + 1,
            'total_questions': len(selected_ids),
            'question': {
                'id': next_question.id,
                'topic': next_question.topic,
                'text': next_question.question_text,
                'options': {
                    'A': next_question.option_a,
                    'B': next_question.option_b,
                    'C': next_question.option_c,
                    'D': next_question.option_d
                }
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500


# ─────────────────────────────────────────
# ENDPOINT 3: Get Summary — supports BOTH
# /api/summary?session_id=X  (query param)
# /api/summary/X             (path param)
# ─────────────────────────────────────────
@api_bp.route('/summary', methods=['GET'])
@api_bp.route('/summary/<int:session_id>', methods=['GET'])
def get_summary(session_id=None):
    # Require a logged-in student (or an admin viewing results).
    owner_id = _current_student_id()
    if owner_id is None and not _is_admin():
        return jsonify({'error': 'Authentication required.'}), 401

    if session_id is None:
        session_id = request.args.get('session_id')

    session_id = _as_int(session_id)
    if session_id is None:
        return jsonify({'error': 'A valid session_id is required'}), 400

    session = Session.query.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # Students may only view their own session summary; admins may view any.
    if not _is_admin() and session.student_id and int(session.student_id) != owner_id:
        return jsonify({'error': 'This quiz session does not belong to you.'}), 403

    # ALGORITHM FIX: Determine weak/strong topics based on PERFORMANCE THRESHOLD
    # A topic is "weak" if accuracy < 50%, "strong" if >= 50%
    
    all_responses = Response.query.filter_by(session_id=session_id).all()
    topic_performance = {}  # {topic_name: {'correct': X, 'total': Y, 'accuracy': Z%}}
    
    # Calculate accuracy per topic
    for response in all_responses:
        resp_question = Question.query.get(response.question_id)
        if resp_question:
            topic = resp_question.topic
            if topic not in topic_performance:
                topic_performance[topic] = {'correct': 0, 'total': 0}
            
            topic_performance[topic]['total'] += 1
            if response.is_correct:
                topic_performance[topic]['correct'] += 1
    
    # Calculate accuracy percentage for each topic
    for topic in topic_performance:
        correct = topic_performance[topic]['correct']
        total = topic_performance[topic]['total']
        accuracy = (correct / total * 100) if total > 0 else 0
        topic_performance[topic]['accuracy'] = accuracy
    
    # Classify as weak (< 50% accuracy) or strong (>= 50% accuracy)
    weak_names = []
    strong_names = []
    
    for topic, perf in topic_performance.items():
        if perf['accuracy'] < 50:
            weak_names.append(topic)
        else:
            strong_names.append(topic)

    correct_count = Response.query.filter_by(session_id=session_id, is_correct=True).count()
    wrong_count = Response.query.filter_by(session_id=session_id, is_correct=False).count()

    return jsonify({
        'status': 'success',
        'weak_topics': weak_names,
        'strong_topics': strong_names,
        'total_correct': correct_count,
        'total_wrong': wrong_count,
        'topic_performance': topic_performance,
        'summary': build_summary(weak_names, strong_names)
    })


# ─────────────────────────────────────────
# ADAPTIVE LOGIC
# ─────────────────────────────────────────
def get_next_question(session_id, subject_id, current_topic, current_difficulty, is_correct, asked_ids, selected_ids=None):
    """
    Adaptive Algorithm - Exact implementation per requirements:
    
    ALGORITHM FLOW:
    ┌─ Easy Question Asked
    ├─ ✓ CORRECT → Hard Question (same topic)
    │  ├─ ✓ CORRECT → New Topic (easy question)
    │  └─ ✗ INCORRECT → Hard Question #2 (same topic)
    │     └─ ✗ INCORRECT → New Topic (mark weak topic) + easy question
    └─ ✗ INCORRECT → New Topic (skip hard) + easy question
    
    RESULT:
    - Hard topic incorrectly answered 2x → WEAK TOPIC
    - Easy topic correctly answered → STRONG TOPIC
    """
    try:
        selected_ids_list = selected_ids if selected_ids else []
        asked_ids_set = set(asked_ids) if asked_ids else set()
        
        # Get all responses for this session organized by topic
        session_responses = db.session.query(Response, Question).join(Question).filter(
            Response.session_id == session_id
        ).all()
        
        # Count hard questions asked per topic
        hard_questions_by_topic = {}
        for resp, q in session_responses:
            if q.difficulty == 'hard':
                if q.topic not in hard_questions_by_topic:
                    hard_questions_by_topic[q.topic] = []
                hard_questions_by_topic[q.topic].append({'correct': resp.is_correct, 'question_id': q.id})
        
        # Validation: Check if we have unanswered questions
        unanswered_ids = [qid for qid in selected_ids_list if qid not in asked_ids_set]
        unanswered_count = len(unanswered_ids)
        
        print(f"\n[ALGO] Session {session_id}: Total={len(selected_ids_list)}, Asked={len(asked_ids_set)}, Unanswered={unanswered_count}")
        print(f"[ALGO] Current: Topic='{current_topic}', Difficulty='{current_difficulty}', IsCorrect={is_correct}")
        
        if unanswered_count == 0:
            print(f"[ALGO] ✓ Quiz Complete - No more unanswered questions")
            return None

        # ═══════════════════════════════════════════════════════════════
        # BRANCH 1: Easy question was asked
        # ═══════════════════════════════════════════════════════════════
        if current_difficulty == 'easy':
            if is_correct:
                print(f"[ALGO] ✓ Easy correct on '{current_topic}' → Ask Hard")
                # Easy correct → Try hard question on same topic
                hard_same_query = Question.query.filter_by(
                    subject_id=subject_id, 
                    topic=current_topic, 
                    difficulty='hard'
                ).filter(Question.id.in_(unanswered_ids))
                hard_same = random_from_query(hard_same_query)
                
                if hard_same:
                    return hard_same
            else:
                print(f"[ALGO] ✗ Easy incorrect on '{current_topic}' → Skip hard, new topic with easy")
                # Easy incorrect → Move to NEW topic with easy (skip hard)
                new_easy = get_new_topic_question(session_id, subject_id, current_topic, 'easy', unanswered_ids)
                if new_easy:
                    return new_easy

        # ═══════════════════════════════════════════════════════════════
        # BRANCH 2: Hard question was asked
        # ═══════════════════════════════════════════════════════════════
        elif current_difficulty == 'hard':
            # Check if this is the 1st or 2nd hard question on this topic
            hard_count_on_topic = len(hard_questions_by_topic.get(current_topic, []))
            
            if is_correct:
                print(f"[ALGO] ✓ Hard correct on '{current_topic}' → New topic with easy")
                # Hard correct → Move to NEW topic with easy
                new_easy = get_new_topic_question(session_id, subject_id, current_topic, 'easy', unanswered_ids)
                if new_easy:
                    return new_easy
            else:
                # Hard incorrect - check if we should retry or mark weak
                print(f"[ALGO] ✗ Hard incorrect on '{current_topic}' (Hard #: {hard_count_on_topic})")
                
                if hard_count_on_topic < 2:
                    # Haven't asked 2 hard questions on this topic yet → Ask Hard #2
                    print(f"[ALGO] → Ask Hard #2 on same topic")
                    hard_retry_query = Question.query.filter_by(
                        subject_id=subject_id, 
                        topic=current_topic, 
                        difficulty='hard'
                    ).filter(Question.id.in_(unanswered_ids))
                    hard_retry = random_from_query(hard_retry_query)
                    
                    if hard_retry:
                        return hard_retry
                else:
                    # Already asked 2 hard questions and both incorrect → Mark weak, move to new topic
                    print(f"[ALGO] → 2 Hard attempts failed. Marking '{current_topic}' as WEAK")
                    # Create weak topic entry
                    session_obj = Session.query.get(session_id)
                    weak = WeakTopic(session_id=session_id, student_id=session_obj.student_id if session_obj else 0, topic=current_topic)
                    db.session.add(weak)
                    db.session.commit()
                    
                    # Move to new topic with easy
                    new_easy = get_new_topic_question(session_id, subject_id, current_topic, 'easy', unanswered_ids)
                    if new_easy:
                        return new_easy

        # Fallback: any unanswered question
        print(f"[ALGO] Using fallback")
        fallback_query = Question.query.filter(Question.id.in_(unanswered_ids))
        fallback = random_from_query(fallback_query)
        if fallback:
            return fallback
        
        print(f"[ALGO] ❌ No valid question found!")
        return None

    except Exception as e:
        print(f"[ALGO] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_new_topic_question(session_id, subject_id, current_topic, difficulty, unanswered_ids):
    """
    Get a question from a NEW TOPIC that hasn't been covered yet.
    Finds topics not in current session and returns question of specified difficulty.
    """
    try:
        unanswered_list = unanswered_ids if isinstance(unanswered_ids, list) else list(unanswered_ids)
        
        # Find topics already covered in this session
        covered_topics = db.session.query(Question.topic).join(Response).filter(
            Response.session_id == session_id, 
            Question.subject_id == subject_id
        ).distinct().all()
        covered_topic_names = [t[0] for t in covered_topics]
        
        # Add current topic to avoid repeating it
        if current_topic not in covered_topic_names:
            covered_topic_names.append(current_topic)
        
        print(f"[NEW_TOPIC] Covered topics: {covered_topic_names}")
        
        # Find question from uncovered topic with specified difficulty
        new_topic_q_query = Question.query.filter_by(
            subject_id=subject_id, 
            difficulty=difficulty
        ).filter(
            ~Question.topic.in_(covered_topic_names),
            Question.id.in_(unanswered_list)
        )
        new_topic_q = random_from_query(new_topic_q_query)
        
        if new_topic_q:
            print(f"[NEW_TOPIC] ✓ Found '{new_topic_q.topic}' ({difficulty}) - Q#{new_topic_q.id}")
            return new_topic_q
        
        # Fallback: any question from uncovered topic (any difficulty)
        any_new_topic_query = Question.query.filter(
            ~Question.topic.in_(covered_topic_names),
            Question.id.in_(unanswered_list),
            Question.subject_id == subject_id
        )
        any_new_topic = random_from_query(any_new_topic_query)
        
        if any_new_topic:
            print(f"[NEW_TOPIC] Fallback: '{any_new_topic.topic}' ({any_new_topic.difficulty}) - Q#{any_new_topic.id}")
            return any_new_topic
        
        # If all topics covered, get any unanswered
        any_unanswered_query = Question.query.filter(
            Question.id.in_(unanswered_list),
            Question.subject_id == subject_id
        )
        any_unanswered = random_from_query(any_unanswered_query)
        
        if any_unanswered:
            print(f"[NEW_TOPIC] All topics covered, using any: '{any_unanswered.topic}' ({any_unanswered.difficulty}) - Q#{any_unanswered.id}")
            return any_unanswered
        
        print(f"[NEW_TOPIC] ❌ No questions available!")
        return None
        
    except Exception as e:
        print(f"[NEW_TOPIC] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_new_topic_question_with_fallback(session_id, subject_id, asked_ids, unanswered_ids):
    """
    Get a question from a new topic the student hasn't covered yet.
    Strict: only returns questions from unanswered_ids
    """
    return get_new_topic_question(session_id, subject_id, "", 'easy', unanswered_ids)


def build_summary(weak_names, strong_names):
    summary = "📊 Quiz Complete! Here's your report:\n\n"
    if strong_names:
        summary += "✅ Strong Topics:\n"
        for t in strong_names:
            summary += f"  • {t}\n"
    if weak_names:
        summary += "\n⚠️ Weak Topics:\n"
        for t in weak_names:
            summary += f"  • {t}\n"
        summary += "\n📝 Please revise your weak topics before your exam. You've got this! 💪"
    else:
        summary += "\n🎉 Excellent! No weak topics. You're fully prepared!"
    return summary
