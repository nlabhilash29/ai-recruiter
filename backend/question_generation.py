from groq import Groq
import os
import re
from typing import List, Dict, Any
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class AIConfigurationError(RuntimeError):
    """Raised when an AI provider is required and not configured."""


def ai_stub_enabled() -> bool:
    return os.getenv("AI_STUB", "").strip().lower() in {"1", "true", "yes", "on"}


# Get API key. The process must still boot when the key is absent so the
# non-AI routes (uploads, session lookup, reports) can run.
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip() or None
# llama3-70b-8192 was shut down on 2025-08-30. Its replacement,
# llama-3.3-70b-versatile, was removed from Groq's developer tier on
# 2026-08-16. openai/gpt-oss-120b is the current recommended model.
GROQ_MODEL = (os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b").strip()
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low").strip()

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
if client is None:
    logger.warning("GROQ_API_KEY is not set. Question generation will use built-in questions.")


def complete_chat(messages: List[Dict[str, str]], max_completion_tokens: int = 2000, temperature: float = 0.4) -> str:
    """Call Groq and return the visible answer text."""
    if client is None:
        raise AIConfigurationError("GROQ_API_KEY is not configured")

    kwargs: Dict[str, Any] = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_completion_tokens,
    }
    if GROQ_REASONING_EFFORT:
        kwargs["reasoning_effort"] = GROQ_REASONING_EFFORT

    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:
        # Some models reject reasoning_effort. Retry once without it.
        if GROQ_REASONING_EFFORT and "reasoning_effort" in str(exc):
            kwargs.pop("reasoning_effort", None)
            response = client.chat.completions.create(**kwargs)
        else:
            raise

    message = response.choices[0].message
    content = (getattr(message, "content", None) or "").strip()
    if not content:
        content = (getattr(message, "reasoning", None) or "").strip()
    return content

async def modify_questions(questions: List[Dict[str, Any]], feedback: str) -> List[Dict[str, Any]]:
    """
    Modify existing questions based on feedback
    """
    try:
        logger.info("Modifying questions based on feedback...")
        
        # Format existing questions for the prompt
        questions_text = "\n".join([
            f"Question {i+1}:\n{q['question_text']}\nType: {q.get('question_type', 'N/A')}\nAssesses: {q.get('assesses', 'N/A')}"
            for i, q in enumerate(questions)
        ])

        prompt = f"""Modify these interview questions based on the following feedback while maintaining their professional structure:

Current Questions:
{questions_text}

Feedback:
{feedback}

Provide modified questions in the same format:
1. Question: [Modified question]
   Type: [Question type]
   Assesses: [Skill/competency]
   Key Points: [Key points to look for in answer]
"""

        if client is None:
            logger.info("Skipping question edits because GROQ_API_KEY is not configured")
            return questions

        generated_text = complete_chat(
            [
                {"role": "system", "content": "You are an expert at refining interview questions based on feedback."},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=2000,
        )

        # Parse the modified questions
        modified_questions = parse_generated_questions(generated_text)
        
        # Validate and clean up modified questions
        validated_questions = []
        for i, q in enumerate(modified_questions):
            if i >= len(questions):  # Don't add more questions than we started with
                break
                
            validated_question = {
                "question_text": q.get("question_text", "").strip(),
                "question_type": q.get("question_type", questions[i].get("question_type", "general")).lower(),
                "assesses": q.get("assesses", questions[i].get("assesses", "general skills")),
                "key_points": q.get("key_points", questions[i].get("key_points", ""))
            }
            
            # Only include valid questions
            if validated_question["question_text"]:
                validated_questions.append(validated_question)
            else:
                # If modification failed, keep the original question
                validated_questions.append(questions[i])

        logger.info(f"Successfully modified {len(validated_questions)} questions")
        return validated_questions

    except Exception as e:
        logger.error(f"Error modifying questions: {str(e)}")
        # Return original questions if modification fails
        logger.info("Returning original questions due to modification error")
        return questions

async def generate_interview_questions(jd_content: str, resume_content: str) -> List[Dict[str, Any]]:
    """
    Generate exactly 5 structured interview questions based on JD and resume using Llama model
    """
    try:
        prompt = f"""Given the job description and resume below, generate EXACTLY 5 interview questions.
Create a diverse set of questions covering:
1. Technical skills and expertise
2. Past experience and achievements
3. Problem-solving abilities
4. Behavioral traits and work style
5. Cultural fit and values

Job Description:
{jd_content}

Resume:
{resume_content}

Provide the questions in this EXACT format:

1. Question: [Ask a specific question related to technical skills mentioned in JD]
   Type: technical
   Assesses: [Specific technical skill]
   Key Points: [3-4 key points to look for in answer]

2. Question: [Ask about relevant past experience]
   Type: experience
   Assesses: [Specific experience area]
   Key Points: [3-4 key points to look for in answer]

3. Question: [Ask about a problem-solving scenario]
   Type: problem-solving
   Assesses: [Problem-solving skill]
   Key Points: [3-4 key points to look for in answer]

4. Question: [Ask about behavioral traits]
   Type: behavioral
   Assesses: [Behavioral trait]
   Key Points: [3-4 key points to look for in answer]

5. Question: [Ask about cultural fit]
   Type: cultural-fit
   Assesses: [Cultural aspect]
   Key Points: [3-4 key points to look for in answer]

Important: Ensure questions are highly specific to the job description and candidate's background.
"""

        if client is None:
            logger.warning("GROQ_API_KEY is not configured. Using default interview questions.")
            return get_default_questions()

        logger.info("Requesting questions from %s...", GROQ_MODEL)
        
        # Make multiple attempts to get good questions
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                generated_text = complete_chat(
                    [
                        {
                            "role": "system",
                            "content": """You are an expert AI recruiter who generates insightful, 
                            specific interview questions based on job descriptions and resumes. 
                            Focus on creating questions that thoroughly evaluate candidate qualifications.
                            Reply with only the five questions in the requested format."""
                        },
                        {"role": "user", "content": prompt}
                    ],
                    max_completion_tokens=4000,
                )

                # Parse the response into structured format
                questions = parse_generated_questions(generated_text)
                
                # Validate the generated questions
                if len(questions) == 5 and all(validate_question(q) for q in questions):
                    logger.info("Successfully generated 5 valid questions from Llama model")
                    return questions
                else:
                    logger.warning(f"Attempt {attempt + 1}: Generated {len(questions)} questions, retrying...")
                    continue

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_attempts - 1:
                    raise

        # If we couldn't get good questions after all attempts, use default questions
        logger.warning("Could not generate valid questions from the configured model, using defaults")
        return get_default_questions()

    except Exception as e:
        logger.error(f"Error in question generation: {str(e)}")
        return get_default_questions()

def validate_question(question: Dict[str, Any]) -> bool:
    """
    Validate that a question has all required fields and appropriate content
    """
    required_fields = ["question_text", "question_type", "assesses", "key_points"]
    
    # Check all required fields are present and non-empty
    if not all(field in question and question[field] for field in required_fields):
        return False
    
    # Validate question text length
    if len(question["question_text"]) < 10:  # Arbitrary minimum length
        return False
    
    # Validate question type
    valid_types = {"technical", "experience", "problem-solving", "behavioral", "cultural-fit"}
    if question["question_type"].lower() not in valid_types:
        return False
    
    return True

def get_default_questions() -> List[Dict[str, Any]]:
    """
    Get default interview questions as fallback
    """
    logger.info("Using default question set")
    return [
        {
            "question_text": "Could you walk me through your most technically challenging project?",
            "question_type": "technical",
            "assesses": "Technical expertise and problem-solving",
            "key_points": "Technical depth, problem approach, solution implementation, results achieved"
        },
        {
            "question_text": "Describe a situation where you had to learn a new technology quickly. How did you approach it?",
            "question_type": "experience",
            "assesses": "Learning ability and adaptability",
            "key_points": "Learning strategy, time management, practical application, outcome"
        },
        {
            "question_text": "Tell me about a time when you had to resolve a complex technical issue under tight deadlines.",
            "question_type": "problem-solving",
            "assesses": "Critical thinking and pressure handling",
            "key_points": "Problem analysis, solution approach, time management, result"
        },
        {
            "question_text": "How do you handle disagreements with team members about technical decisions?",
            "question_type": "behavioral",
            "assesses": "Conflict resolution and teamwork",
            "key_points": "Communication style, conflict resolution approach, team collaboration, outcome"
        },
        {
            "question_text": "What aspects of our company's tech stack and culture interest you the most?",
            "question_type": "cultural-fit",
            "assesses": "Company culture alignment and technical interest",
            "key_points": "Company research, technical knowledge, cultural values, motivation"
        }
    ]

def parse_generated_questions(text: str) -> List[Dict[str, Any]]:
    """
    Parse the LLM response into structured question objects
    """
    questions = []
    current_question = {}
    
    try:
        text = (text or "").replace("**", "").replace("__", "")
        for line in text.split('\n'):
            line = line.strip().lstrip("-").strip()
            if not line:
                continue
            
            # Check for new question
            numbered = len(line) > 2 and line[0].isdigit() and line[1] == "."
            if line.startswith('Question:') or numbered:
                if current_question and 'question_text' in current_question:
                    questions.append(current_question)
                current_question = {
                    "question_text": line.split(':', 1)[1].strip() if ':' in line 
                    else line.split('.', 1)[1].strip()
                }
            elif line.startswith('Type:'):
                current_question['question_type'] = line.replace('Type:', '').strip().lower()
            elif line.startswith('Assesses:'):
                current_question['assesses'] = line.replace('Assesses:', '').strip()
            elif line.startswith('Key Points:'):
                current_question['key_points'] = line.replace('Key Points:', '').strip()
        
        # Add the last question
        if current_question and 'question_text' in current_question:
            questions.append(current_question)
        
        # Additional validation and cleanup
        validated_questions = []
        for q in questions:
            if validate_question(q):
                validated_questions.append(q)
        
        return validated_questions
        
    except Exception as e:
        logger.error(f"Error parsing questions: {str(e)}")
        return []

def heuristic_analysis(question: str, response_text: str) -> Dict[str, Any]:
    """Local scoring used when AI_STUB is on and no Groq key is available."""
    words = [word for word in response_text.split() if word]
    length_score = min(10.0, max(3.0, len(words) / 8))
    question_terms = {word.lower().strip(".,?") for word in question.split() if len(word) > 4}
    overlap = sum(1 for word in words if word.lower().strip(".,?") in question_terms)
    relevance = min(10.0, length_score + min(2.0, overlap))
    return {
        "relevance_score": round(relevance, 1),
        "clarity_score": round(min(10.0, 4 + len(words) / 12), 1),
        "technical_score": round(length_score, 1),
        "key_points": "",
        "improvement_areas": "Connect GROQ_API_KEY for model-written coaching.",
        "feedback": "Stub analysis because AI_STUB is enabled. Set GROQ_API_KEY for real scoring.",
    }


async def analyze_response(question: str, response: str) -> Dict[str, Any]:
    """
    Analyze a candidate's response to a question
    """
    try:
        if client is None:
            if ai_stub_enabled():
                return heuristic_analysis(question, response)
            raise AIConfigurationError("GROQ_API_KEY is not configured")

        prompt = f"""Analyze this interview response based on the following criteria:
1. Relevance to the question (0-10)
2. Clarity of communication (0-10)
3. Technical accuracy (if applicable) (0-10)
4. Key points covered
5. Areas for improvement

Question: {question}
Response: {response}

Provide analysis in the following format:
Relevance Score: [score]
Clarity Score: [score]
Technical Score: [score]
Key Points Covered: [points]
Improvement Areas: [areas]
Overall Feedback: [feedback]
"""

        analysis_text = complete_chat(
            [
                {"role": "system", "content": "You are an expert at evaluating interview responses. Reply using the requested labels only."},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=1500,
        )

        # Parse the analysis
        analysis = parse_response_analysis(analysis_text)
        return analysis

    except AIConfigurationError:
        raise
    except Exception as e:
        logger.error(f"Error analyzing response: {str(e)}")
        # Return default scores if analysis fails
        return {
            'relevance_score': 5,
            'technical_score': 5,
            'clarity_score': 5,
            'feedback': 'Error analyzing response',
            'improvement_areas': 'Analysis unavailable',
            'key_points': ''
        }

def _parse_score(raw: str, default: float = 5.0) -> float:
    match = re.search(r"\d+(?:\.\d+)?", raw or "")
    if not match:
        return default
    try:
        return max(0.0, min(10.0, float(match.group(0))))
    except ValueError:
        return default


def parse_response_analysis(text: str) -> Dict[str, Any]:
    """
    Parse the response analysis into a structured format
    """
    analysis = {
        'relevance_score': 5,
        'clarity_score': 5,
        'technical_score': 5,
        'key_points': '',
        'improvement_areas': '',
        'feedback': ''
    }
    
    try:
        text = (text or "").replace("**", "")
        for line in text.split('\n'):
            line = line.strip().lstrip("-").strip()
            if line.lower().startswith('relevance score:'):
                analysis['relevance_score'] = _parse_score(line.split(':', 1)[1])
            elif line.lower().startswith('clarity score:'):
                analysis['clarity_score'] = _parse_score(line.split(':', 1)[1])
            elif line.lower().startswith('technical score:'):
                analysis['technical_score'] = _parse_score(line.split(':', 1)[1])
            elif line.lower().startswith('key points covered:'):
                analysis['key_points'] = line.split(':', 1)[1].strip()
            elif line.lower().startswith('improvement areas:'):
                analysis['improvement_areas'] = line.split(':', 1)[1].strip()
            elif line.lower().startswith('overall feedback:'):
                analysis['feedback'] = line.split(':', 1)[1].strip()
    except Exception as e:
        logger.error(f"Error parsing analysis: {str(e)}")
    
    return analysis