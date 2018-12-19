# anyreduce

anyreduce is an experimental new test case reducer. It's currently not very interesting.

Long-run the idea is that it will be a principled hybrid of:

* Good general purpose reduction algorithms that work on a variety of file formats.
* A mix of format-specific heuristics.

Right now its heuristics are fairly specifically tuned for C-like languages, so it's mostly a worse version of C-reduce.
I wouldn't recommend using it yet.
