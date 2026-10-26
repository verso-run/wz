# Review: Larkspur Tool Library discussion guide

Verdict: CHANGES NEEDED

This is a good guide. The questions ask for stories ("Tell me about the last time..."), there is no jargon, the facts come before the one opinion question (Q9), and the consent script covers recording, stopping, privacy and no wrong answers. The committee's five leading, double-barrelled and jargon questions were all dropped or replaced, and the guide says so.
Three questions (Q4, Q6, Q8) and one probe (Q7) still lean on an assumption, so they need a small rewrite. The timing is also stated wrongly: no one is asked all the questions, so the real length is about 32 minutes, not 38. Two lines in the consent script promise things the committee has not agreed to.
`guide-check` and `lint` found nothing (32 questions and probes read, 0 flags); the findings below come from reading every question myself.

## Findings
| Where | Question | Flag | Why | Method source | Suggested rewrite |
|---|---|---|---|---|---|
| Q4 | "Tell me about a time you thought of using it." | leading | It assumes the person did think of using the shelf. Someone who never did has to say "no" or invent a time, and this may be exactly the group that Goal 3 needs to hear from. | M3, M1 | "Tell me about any time the tool shelf crossed your mind when you needed a tool." |
| Q6 | "Tell me about the last time you thought of borrowing something from the shelf." | leading | It assumes they thought of borrowing. Some people stopped because they moved or forgot, and never thought of it again. The question also skips the last time they did borrow, which is the best fact for Goal 2. | M3, M1 | "Tell me about the last time you borrowed something from the shelf." Keep the current wording as a follow-up probe, with "if there was a time". |
| Q8 | "Tell me about anything you would need to sort out before going to the hall." | leading | It assumes there are things to sort out, so it steers people toward barriers. It is also a "what would you do" question, so it gets guesses about the future and not something that happened. | M3, M1 | "Tell me about what getting to the hall involves for you, from leaving home to getting back." Or: "Tell me about the last time you went to the hall for something." |
| Q7 | "How would going to the hall fit into that week?" | leading | This is a probe under Q7. It asks a Group A person to imagine joining, and it hints that fitting it in is the issue, which is the committee's own belief about opening hours. Probes should stay neutral. | M1, M2 | Drop it. Use "Tell me more about that" or "Can you give me an example?". |

## Other findings (not about one question's wording)
These did not fit the flag column, which allows only leading, double-barrelled, jargon, yes/no and long.
- **Timing, section 5 heading "Core questions — 28 min total" and the header "Total time: 38 minutes".** The 28 minutes add 5.2 (Group A, 6 min) and 5.3 (Group B, 6 min), but each person is asked only one of them. A real interview is 3 + 3 + 22 + 4 = 32 minutes. The guide's own note says each person is asked seven questions, so the totals contradict it. Fix the totals. The spare time can go to the busiest block: 5.4 has Q7, Q8 and Q9 with eight probes in 8 minutes, which is tight for a first-time interviewer who is a good listener. Source: M1 ("keep your interviews within an hour"; leave room for follow-ups); M2 on leaving time for a closing question. Whether 8 minutes is enough in practice is a judgement; the methods base gives no per-block figures (not covered by the methods base).
- **Consent script, the retention and listener lines.** "Only I and the small group of committee members working on this will hear it" and "we will delete the recording and keep only typed notes with no names on them" are read aloud as promises. The guide itself says the committee has not agreed the retention line. The guide has an "[ask them: ...]" marker, which is right, but the script should not be read as it stands until the committee confirms both lines. The script otherwise covers recording, stopping, privacy and no wrong answers (M2: "there are no wrong answers"; "ask permission to record the interview and take notes").
- **Goal 2 coverage.** Goal 2 ("What people who joined and then stopped borrowing ran into") has Q5, Q6, Q7 and Q8 but no question about when and how they stopped. Changing Q6 as above fixes most of this. A probe such as "What happened after that?" would let Mara hear the stopping story.
- **Probe word on the card.** The card says "Use the probes only if the answer is short". "Probes" is researcher language for a reader who has never run an interview, and the guide's jargon list does not include it. Say "follow-up questions". Plain language is covered by M6.

## Goals and questions
- Goal 1, how neighbours get hold of a tool they need once or twice: Q1 and Q2 (with their probes) answer it. Fine.
- Goal 2, what people who joined and then stopped ran into: Q5 and Q6 (Group B), with Q7 and Q8 for everyone. Partly covered; see the Q6 finding and the coverage note above.
- Goal 3, what has stopped neighbours who have heard of the shelf from coming in: Q3 and Q4 (Group A), with Q7 and Q8. Covered once Q4 and Q8 are made neutral.

## Checked and fine
- Order: warm-up, then facts (Q1 to Q8), then the one opinion question (Q9), then the closing. This follows M2 (facts before opinions) and M1 (general first).
- W1 and its probes ("How long have you been here?", "What do you like about the area?"). The first probe is one short fact and is fine.
- Q1 and its probes. Q2 and its probes. Q3 and its probes ("Where did you hear about it?", "What did you take it to be?"). Q4 probes ("What happened next?", "What did you do in the end?"). Q5 and its probes. Q6 probes ("What happened?", "What did you do instead?"). Q7 and its first two probes. Q8 probe ("Can you give me an example?"). Q9 and its probes ("What makes you say that?", "Tell me more about that.").
- Q9 asks for a view, but it is hypothetical and last, so it is fine.
- C1 "Is there anything we have not talked about that you think I should know?" is a yes/no in form, but it is the usual closing catch-all and people answer it with more than yes or no. M2 supports a closing question ("Finish, time permitting, with a question such as"). Kept as fine.
- Words in the questions match the audience file ("borrow", "tool shelf", "the hall"). The jargon words (inventory, onboarding, membership model, stakeholders, lapsed) do not appear in any question.
- Sensitive topics: no question asks about money, income or housing. The card says to follow the person's lead on health or mobility.
- The card is consistent with the probes: it says to stay silent, not to help, and to answer library questions after the interview.
- Recruitment keeps the two groups clear of volunteers and recent borrowers, and offers a phone or home visit for the step. The voucher is given whether or not every question is answered.

## Checker flags I dismissed
- None. `guide-check` and `lint` raised no flags, and `review-check` is run at the end.
- The recording permission question in the consent script ("Is it all right if I record?") is yes/no on purpose, because consent needs a clear yes (M2).

## What I could not check
- Whether Mara can read the consent script in about 3 minutes. It looks about right on length, but this needs a trial read.
- Mara runs the Wednesday session and will personally invite lapsed members. People may soften what they say to someone from the library. The methods base has no source on this (not covered by the methods base). The committee could consider whether someone else should do Group B interviews.
- Whether telling people at the close that the committee "decides in January how to use a small grant" raises hopes. The methods base does not cover it (not covered by the methods base).
- The guide's own notes (section 8) were not checked against the committee-notes file beyond the five questions listed there.
