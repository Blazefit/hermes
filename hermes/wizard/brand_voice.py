"""Brand voice document generator for Hermes.

Generates a starter brand-voice.md file based on business details
and communication preferences collected during setup.
"""

from __future__ import annotations

from typing import List


def generate_brand_voice(
    business_name: str,
    owner_name: str,
    location: str = "",
    website: str = "",
    phone: str = "",
    tone: str = "friendly",
    industry: str = "",
    always_mention: List[str] | None = None,
    never_say: List[str] | None = None,
) -> str:
    """Generate a brand voice markdown document.

    Args:
        business_name: Name of the business.
        owner_name: Name of the owner/operator.
        location: Business location (city, state).
        website: Business website URL.
        phone: Phone number(s).
        tone: Communication tone -- "formal", "casual", or "friendly".
        industry: Industry or business type.
        always_mention: List of things to always include in emails.
        never_say: List of things to never include in emails.

    Returns:
        Markdown string for the brand voice document.
    """
    always_mention = always_mention or []
    never_say = never_say or []

    owner_first = owner_name.split()[0] if owner_name else "the team"

    # Tone descriptions
    tone_descriptions = {
        "formal": (
            "Professional and polished. Use complete sentences, proper grammar, "
            "and a respectful but warm tone. Avoid slang or overly casual language."
        ),
        "casual": (
            "Relaxed and conversational. Write like you're texting a friend who "
            "happens to be a customer. Short sentences, contractions, and a "
            "natural flow."
        ),
        "friendly": (
            "Warm and personal. Strike a balance between professional and "
            "approachable. Use the sender's first name, write in first person, "
            "and let personality come through."
        ),
    }
    tone_desc = tone_descriptions.get(tone, tone_descriptions["friendly"])

    # Build the always-mention section
    always_section = ""
    if always_mention:
        items = "\n".join(f"- {item}" for item in always_mention)
        always_section = f"""
## Always Mention
When relevant and natural, include:
{items}
"""

    # Build the never-say section
    never_section = ""
    if never_say:
        items = "\n".join(f"- {item}" for item in never_say)
        never_section = f"""
## Never Say
These words, phrases, or topics should never appear in outgoing emails:
{items}
"""

    # Build contact info section
    contact_lines = []
    if location:
        contact_lines.append(f"- Location: {location}")
    if website:
        contact_lines.append(f"- Website: {website}")
    if phone:
        contact_lines.append(f"- Phone: {phone}")

    contact_section = ""
    if contact_lines:
        items = "\n".join(contact_lines)
        contact_section = f"""
## Contact Information
Include when relevant:
{items}
"""

    industry_line = f" in the {industry} industry" if industry else ""

    return f"""# Brand Voice: {business_name}

## Identity
- **Business:** {business_name}{industry_line}
- **Voice:** {owner_first} -- the person behind the emails
- **Sign-off name:** {owner_first}

## Tone & Style
{tone_desc}

### Writing Guidelines
- Write as {owner_first}, not "the {business_name} team"
- Use first person ("I" not "we") unless the context calls for "we"
- Address the recipient by their first name
- Keep emails concise -- say what needs to be said, then stop
- One clear call to action per email
- No corporate jargon, no buzzwords, no filler phrases
{contact_section}
## Email Structure
1. **Greeting:** Warm, personal, uses their name
2. **Acknowledgment:** Reference what they wrote about
3. **Response:** Answer their question or address their need
4. **Next step:** One clear action they can take
5. **Close:** Casual sign-off with {owner_first}'s name
{always_section}{never_section}
## Universal Rules
- Never fabricate information -- if unsure, flag for review
- Never make financial commitments or promises
- Never use urgency tactics or hard-sell language
- Never include information not verified in the template or config
- Always match the energy of the sender -- if they're excited, be excited back
- If a question can't be confidently answered, say so honestly

## Formatting
- No bullet points in customer-facing emails (they feel like form letters)
- Short paragraphs (2-3 sentences max)
- One blank line between paragraphs
- No signatures with titles, logos, or disclaimers unless required
"""
