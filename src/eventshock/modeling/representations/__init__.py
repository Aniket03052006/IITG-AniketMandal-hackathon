"""Text representations for the event model and the affect channels, compared on one protocol (Stage 4, ``configs/evidence_v2.yaml``).

Channels: **K** keyword (TF-IDF, the shipped baseline), **L** finance lexicon counts, **S** dense semantic sentence embeddings (frozen),
**A** affect (finance tone and general emotion class probabilities from frozen classifiers). ``encoders`` needs torch and runs only in the
optional ``.venv-emb``; it writes an on-disk cache that every other module (main venv, numpy/sklearn only) reads, so the product never imports torch.
"""
