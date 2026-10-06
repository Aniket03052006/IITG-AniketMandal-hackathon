"""External market intelligence: what an independent market currently appears to price about an event's theme. A derived, descriptive side-car.

Kalshi (a regulated prediction market) is the first provider; the abstraction (``ExternalMarketObservation`` and ``MarketProvider``) does not assume it. Nothing here feeds the risk signal,
the severity score, the classification, portfolio mapping or any stress: a market price is an observation worth monitoring, not a ground truth and never an input.
"""
