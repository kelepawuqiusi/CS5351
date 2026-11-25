# Individual Reflection — Member D

My task looked simple at the start: run the system twice and report the numbers. It turned out
that almost none of the difficulty was in running it. The difficulty was deciding what a number
means, and refusing to report ones I could not defend.

The first thing I had to unlearn was trusting the interface. The CLI panel is convenient and it
was what I reached for first, but it reported 106.2k input tokens where the graph had actually
consumed 114.9k. If I had used the panel, an 8% increase would have looked like a 20% increase
and someone would have spent a week chasing a problem that did not exist. That single
discrepancy taught me to attach the counter to the computation rather than to the display, and
to state in the record which one I used.

The second lesson was about variance. Three runs under one frozen configuration produced
137.2k, 153.4k and 154.5k total tokens. One run would have let me tell any story I liked. I
reported the spread and the two stalled runs I excluded instead of quietly averaging them away,
because a number that hides its denominator is not evidence, it is decoration. A teammate can
disagree with my spread; they cannot recompute a number I never gave them.

The third lesson came from attribution. Grouping cost by stage told us roughly where the tokens
went, but only the per-call trace showed why: input inside the analyst loop grows from about
2k to 19k as each round re-sends the accumulated transcript. I also found that the graph labels
every agent call with the same generic node name, so the owner has to be recovered from the
checkpoint prefix. That was my own tooling being wrong, and I would have published a
misleading table if I had not checked it.

The last lesson was harder and more useful: measuring is a service, not a conclusion. Three of
the performance and cost requirements turned out to be unenforceable in this semester's code,
and one of them was mine to say so about. Telling the team that a requirement I had helped
write could not be met was less comfortable than reporting a clean average, but a cap that
fails on ordinary variance is worse than an honest provisional cap. I also learned to separate
a measurement defect from an infrastructure defect when two calls hung for ten minutes, because
the record has to be usable by someone who was not there.

What I would do differently: freeze and verify the measurement harness in its own reviewed
file before the first run, and repeat the attribution before quoting decimals. What I keep:
report the denominator, the exclusions and the range, every time.
