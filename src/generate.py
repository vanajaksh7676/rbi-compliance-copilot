"""Ask the LLM to answer only from the retrieved paragraphs, with numbered citations.
The provider (OpenAI or Groq) is chosen in .env: see providers.py."""
import providers

NOT_FOUND = "I could not find this in the RBI directions I have."

SYSTEM = f"""You answer questions about RBI Master Directions for commercial banks.
Use ONLY the numbered sources provided. After every sentence that uses a source, cite it like [2].
If the sources do not contain the answer, reply exactly: "{NOT_FOUND}"
Never use outside knowledge. Copy numbers (amounts, percentages, days) exactly as written.
If a source has a note saying it was amended or deleted, mention that.
Keep the answer under 150 words."""


def build_prompt(question, chunks):
    blocks = []
    for i, c in enumerate(chunks, start=1):
        notes = "".join(f"\nNote: {n}" for n in c.get("notes", []))
        blocks.append(f"[{i}] {c['title']}, para {c['para']} (page {c['page']})\n"
                      f"Section: {c.get('section', '')}\n{c['text']}{notes}")
    return "Sources:\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"


def generate(question, chunks):
    """Returns (answer, tokens used)."""
    return providers.chat(SYSTEM, build_prompt(question, chunks))
