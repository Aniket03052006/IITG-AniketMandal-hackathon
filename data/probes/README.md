# Finance polarity probe

Sixty hand-written sentences in thirty minimal pairs (`finance_polarity_pairs.jsonl`). Each pair shares a trigger word or theme whose
meaning flips with the finance context (for example "crushing earnings" vs "a crushing debt load"); `polarity` is +1 when the sentence is
good news for the named company's shareholders and -1 when it is bad news. The text is original (written for this project), the companies are
the 34 issuers of the entity master, and nothing in it is a real headline.

Use: a diagnostic of *context sensitivity* for each text channel (sentiment model, finance-tone model, emotion model, lexicon): the share of
pairs whose positive sentence scores above its negative sentence. It is never used for model selection (it is small and was written by the
same author who designed the study), only reported.
