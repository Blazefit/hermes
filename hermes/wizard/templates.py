"""Template generator for Hermes email categories.

Generates a markdown template anchor file for a given category,
populated with the business name and owner name.
"""

from __future__ import annotations


def generate_category_template(
    business_name: str,
    owner_name: str,
    category_slug: str,
    category_display: str,
) -> str:
    """Generate a markdown template for a single email category.

    Args:
        business_name: Name of the business (e.g. "Acme Fitness").
        owner_name: Name of the owner/operator (e.g. "Jane").
        category_slug: URL-safe category name (e.g. "inquiry").
        category_display: Human-readable category name (e.g. "General Inquiry").

    Returns:
        Markdown string for the template anchor file.
    """
    owner_first = owner_name.split()[0] if owner_name else "the team"

    return f"""# Template Anchor: {category_display}

## Purpose
Respond to emails categorized as **{category_display}** for {business_name}.
This template guides the AI in generating appropriate, on-brand replies.

## Tone
Warm, professional, and helpful. Write as {owner_first} would -- a real person
who cares about the customer, not a faceless company.

## What the Reply Should Do
1. Acknowledge the sender's message and what they're asking about
2. Provide helpful, accurate information relevant to their {category_slug} request
3. Offer a clear next step or call to action
4. Close warmly with a personal sign-off

## Required Information
- Address the sender by name when available
- Reference specifics from their original email
- Include relevant contact information for {business_name}

## Sign-Off
Casual and personal:
> {owner_first}

## Never
- Sound robotic, corporate, or like a form letter
- Make promises or commitments without verification
- Include information you're not confident about
- Use jargon the sender wouldn't understand
- Forget to actually answer what they asked

## Guardrails
- If the email contains a question you can't confidently answer, flag it for review
- If financial details are involved, always flag for human review
- Keep replies concise -- aim for 4-8 sentences unless more detail is needed

## Example Flow
1. Warm greeting acknowledging their message
2. Direct response to their question or request
3. Any additional helpful context
4. Clear next step
5. Friendly close
"""


def generate_uncategorized_template(
    business_name: str,
    owner_name: str,
) -> str:
    """Generate the special uncategorized fallback template.

    Args:
        business_name: Name of the business.
        owner_name: Name of the owner/operator.

    Returns:
        Markdown string for the uncategorized template.
    """
    owner_first = owner_name.split()[0] if owner_name else "the team"

    return f"""# Template Anchor: Uncategorized

## Purpose
Fallback template for emails that don't clearly fit any other category.
These should ALWAYS be flagged for manual review.

## Tone
Polite and neutral. Acknowledge the email without making assumptions
about what the sender needs.

## What the Reply Should Do
1. Thank the sender for reaching out to {business_name}
2. Acknowledge that you've received their message
3. Let them know someone will follow up personally
4. Provide a direct contact method

## Guardrails
- ALWAYS flag for review -- never auto-send uncategorized emails
- Do not attempt to classify or guess the intent
- Keep the response brief and non-committal

## Sign-Off
> {owner_first}

## Never
- Guess at what the sender wants
- Make any commitments or promises
- Auto-send without human review
"""
