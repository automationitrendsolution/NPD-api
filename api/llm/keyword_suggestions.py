"""
Keyword Suggestions — AI-generated keyword expansion for a seed term.

Given a seed keyword (e.g. "shirts"), uses GPT-4o-mini to generate
a structured set of keyword suggestions grouped by category:
  - Color / finish variants
  - Style / type variants
  - Material variants
  - Audience / demographic variants
  - Use-case / occasion variants
  - Brand-style / premium variants
  - Amazon long-tail combinations

Each suggestion is a ready-to-use Amazon search keyword.
"""

from .client import MODEL_FAST, call_llm

SYSTEM_PROMPT = """You are an Amazon keyword research expert specialising in FBA product launches.

Your job is to expand a seed keyword into a comprehensive set of search keywords
that real Amazon buyers type when shopping in that category.

RULES:
1. All keywords must be realistic Amazon search terms — things buyers actually type.
2. Group keywords into meaningful categories relevant to the seed product.
3. Include both short-tail (2-3 words) and long-tail (4-6 words) variants.
4. Include brand-style variants where relevant (premium, budget, brand-name style).
5. Return ONLY valid JSON matching the exact schema requested. No markdown, no commentary.
"""


def generate_keyword_suggestions(seed_keyword: str) -> dict:
    """
    Generates AI keyword suggestions for a given seed keyword.

    Parameters
    ----------
    seed_keyword : str
        The seed product term, e.g. "shirts", "bamboo mug", "dog leash"

    Returns
    -------
    dict with keys:
        seed_keyword   : str
        total_keywords : int
        groups         : list of {
            category       : str   (e.g. "Color Variants")
            icon           : str   (Bootstrap icon class, e.g. "bi-palette")
            keywords       : list of {
                keyword    : str
                type       : "short_tail" | "long_tail"
                notes      : str  (brief rationale, 1 sentence)
            }
        }
        amazon_top_picks : list[str]   (top 5 highest-opportunity keywords)
        search_tips      : str         (1-2 sentences on keyword strategy)
    """
    user_prompt = f"""
Seed keyword: "{seed_keyword}"

Generate comprehensive Amazon keyword suggestions for this product category.
Think about what real buyers type when searching on Amazon.

Return JSON with EXACTLY this structure:

{{
  "seed_keyword": "{seed_keyword}",
  "total_keywords": 0,
  "groups": [
    {{
      "category": "Color / Finish Variants",
      "icon": "bi-palette",
      "keywords": [
        {{
          "keyword": "white {seed_keyword}",
          "type": "short_tail",
          "notes": "High search volume, colour is a top filter on Amazon"
        }}
      ]
    }},
    {{
      "category": "Style / Type Variants",
      "icon": "bi-grid",
      "keywords": []
    }},
    {{
      "category": "Material Variants",
      "icon": "bi-droplet",
      "keywords": []
    }},
    {{
      "category": "Audience / Demographic",
      "icon": "bi-people",
      "keywords": []
    }},
    {{
      "category": "Use Case / Occasion",
      "icon": "bi-calendar-event",
      "keywords": []
    }},
    {{
      "category": "Brand Style / Premium",
      "icon": "bi-award",
      "keywords": []
    }},
    {{
      "category": "Amazon Long-Tail",
      "icon": "bi-search",
      "keywords": []
    }}
  ],
  "amazon_top_picks": [
    "top keyword 1",
    "top keyword 2",
    "top keyword 3",
    "top keyword 4",
    "top keyword 5"
  ],
  "search_tips": "1-2 sentence strategy tip for this specific product category on Amazon."
}}

Fill ALL groups with 4-8 realistic keywords each.
Set total_keywords to the actual count of all keywords across all groups.
Only include groups that make sense for this product — skip irrelevant ones (e.g. no "Color Variants" for a purely digital product).
""".strip()

    result = call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=MODEL_FAST,
        temperature=0.5,
        json_mode=True,
        label="keyword_suggestions",
    )

    result["seed_keyword"] = seed_keyword
    return result
