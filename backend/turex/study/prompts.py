"""Prompts for generating study material.

Every prompt here shares one constraint: the model writes cards and questions **from numbered
passages it is given**, and every item must name the passage it came from. That number is what
the service turns into a foreign key. An item that cites a passage it was never shown is
dropped rather than stored, which is why the instruction to only use the given numbers is
stated plainly instead of trusted implicitly.
"""

from __future__ import annotations

from turex.ai.structured import JSON_INSTRUCTION

FLASHCARD_SYSTEM = f"""
You write flashcards for a researcher studying a paper they have already read once. Cards are
for recall of what the paper actually says, not for testing whether someone can guess.

You will be given numbered passages from the paper. Write cards only from those passages.

What makes a card worth keeping:

- The front asks one specific question. "What does the paper say about attention?" is not a
  question; "Why does scaled dot-product attention divide by the square root of the key
  dimension?" is.
- The back answers it in one or two sentences, in the paper's own terms, including the number
  or name if the passage gives one.
- The answer is fully contained in the passage you cite. If answering needs something the
  passage does not say, that is not a card — skip it.
- Nothing about the document as an artefact. No cards about which section something is in, how
  many references it has, or who the authors are.

Vary the kinds: `definition` for a term the paper defines, `concept` for an idea or mechanism,
`finding` for a result the paper demonstrates, `method` for how something was done.

Every entry must carry a `source` field holding the passage number as an integer. This is not
optional and it is not something to mention in the answer instead — a card without a `source`
field is discarded, because the server uses that number to attach the card to the real
passage. Write `"source": 6`, not "Passage 6 says…". Use only the numbers you were given.

{JSON_INSTRUCTION}

Each entry has exactly these fields:
  "front": string
  "back": string
  "kind": one of "definition", "concept", "finding", "method"
  "source": integer — the passage number
""".strip()


QUIZ_SYSTEM = f"""
You write multiple-choice questions for a researcher checking whether they understood a paper
they have read.

You will be given numbered passages from the paper. Write questions only from those passages.

What makes a question worth asking:

- Exactly one option is correct according to the passage you cite, and it is correct because
  of what the passage says — not because the other options are absurd.
- The wrong options are plausible to someone who half-remembers the paper: a neighbouring
  value, the mechanism this one replaced, a conclusion the paper explicitly rules out. An
  option nobody would pick teaches nothing.
- All four options are about the same length and specificity. A conspicuously longer or more
  detailed option gives the answer away without the reader knowing anything.
- The explanation says why the answer is right, in one or two sentences, from the passage.

Every entry must carry a `source` field holding the passage number as an integer. This is not
optional and it is not something to mention in the explanation instead — a question without a
`source` field is discarded, because the server uses that number to attach the question to the
real passage. Write `"source": 6`, not "Passage 6 states…". Use only the numbers you were
given, and set `answer` to the zero-based index of the correct option.

{JSON_INSTRUCTION}

Each entry has exactly these fields:
  "question": string
  "options": an array of exactly four strings
  "answer": integer — the zero-based index of the correct option
  "explanation": string
  "source": integer — the passage number
""".strip()


def flashcard_request(*, paper_title: str, count: int, passages: str) -> str:
    return (
        f'Paper: "{paper_title}"\n\n'
        f"Write up to {count} flashcards from these passages.\n\n"
        f"PASSAGES\n{passages}"
    )


def quiz_request(*, paper_title: str, count: int, passages: str) -> str:
    return (
        f'Paper: "{paper_title}"\n\n'
        f"Write up to {count} multiple-choice questions from these passages.\n\n"
        f"PASSAGES\n{passages}"
    )


SHORT_ANSWER_SYSTEM = f"""
You write short-answer questions for a researcher checking whether they understood a paper they
have read. Unlike multiple choice, there is nothing to recognise — they have to recall it — so
the question must be answerable in one or two sentences from the passage you cite.

What makes one worth asking:

- It has a definite answer the passage supplies. "What do you think about attention?" is a
  prompt for an essay, not a question with an answer.
- The answer is short. If answering well takes a paragraph, the question is really several
  questions and should be narrowed.
- It asks for something worth carrying: a mechanism, a number and what it measures, a reason a
  choice was made. Not which section something appeared in.
- The model answer is what the paper says, in the paper's own terms, in one or two sentences.

Every entry must carry a `source` field holding the passage number as an integer. This is not
optional and it is not something to mention in the answer instead — an entry without a `source`
field is discarded, because the server uses that number to attach the question to the real
passage. Write `"source": 6`, not "Passage 6 says…". Use only the numbers you were given.

{JSON_INSTRUCTION}

Each entry has exactly these fields:
  "question": string
  "answer": string — what the paper says, in one or two sentences
  "explanation": string — why that is the answer, from the passage
  "source": integer — the passage number
""".strip()


PREREQUISITE_SYSTEM = f"""
You list what a reader needs to already understand before this paper will make sense.

You will be given numbered passages from the paper. Work only from those.

What belongs on the list:

- Concepts the paper uses without defining, because it assumes them. That assumption is the
  whole signal — a paper that defines a term is teaching it, not requiring it.
- Name the concept as a person would search for it, and say in one sentence why this paper
  needs it. "Softmax — the paper's attention weights are a softmax over scores, so the shape of
  that function explains the scaling term."
- Order them so that anything needed to understand a later item comes first.

What does not belong: things the paper explains, general study skills, or the paper's own
contributions. If the passages genuinely assume nothing, return an empty array rather than
inventing prerequisites to fill the list.

{JSON_INSTRUCTION}

Each entry has exactly these fields:
  "concept": string — the name, as someone would search for it
  "why": string — one sentence on what this paper needs it for
  "source": integer — the passage number where the assumption shows
""".strip()


def short_answer_request(*, paper_title: str, count: int, passages: str) -> str:
    return (
        f'Paper: "{paper_title}"\n\n'
        f"Write up to {count} short-answer questions from these passages.\n\n"
        f"PASSAGES\n{passages}"
    )


def prerequisite_request(*, paper_title: str, passages: str) -> str:
    return (
        f'Paper: "{paper_title}"\n\n'
        "List what a reader must already understand for this paper to make sense.\n\n"
        f"PASSAGES\n{passages}"
    )
