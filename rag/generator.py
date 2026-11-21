from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

def get_rag_response(user_query: str) -> str:
    try:
        # basic information for demonstration purposes, replace this with quadrant and neo4j
        mock_tku_context = """
        [Tamkang University (TKU) Information Base - Sample]
        - Library Hours: Mon-Fri 08:00 - 22:00, Sat-Sun 09:00 - 17:00.
        - Dormitory Application: Students can apply online via the TKU student portal before August each year.
        - Campus Locations: Tamsui Campus (Main campus, New Taipei City), Taipei Campus, Lanyang Campus.
        - Languages supported: Traditional Chinese and English.
        - Department of Computer Science and Information Engineering: Location at Tamsui Campus, building E, Room 646
        """

        # Prompt engineering for the RAG response
        prompt = f"""
        You are an official AI QnA Assistant for Tamkang University (TKU). 
        Answer the user's question accurately based ONLY on the provided context below. 
        If the answer is not in the context, politely state that you are still indexing more public data.
        Answer in both languages. Traditional Chinese at first then the answer in English is below it.
        Answer in both languages. Traditional Chinese at first then the answer in English is below it.
        Answer directly, like a helpful staff member. Never mention the context, database,
        information base, or phrases such as "according to" or "based on the provided information".
        {mock_tku_context}

        User Question: {user_query}
        """

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return response.text
        
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return "AI system is busy"