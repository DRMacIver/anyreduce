import hashlib
import attr
import anyreduce.sequencepasses as sequences
from collections import Counter, defaultdict
import re
import bisect
import heapq


def cache_key(value):
    return int.from_bytes(hashlib.sha1(value).digest()[:8], "big")


def sort_key(b):
    return (len(b), b)


def to_bs(c):
    if isinstance(c, int):
        c = bytes([c])
    assert isinstance(c, bytes)
    return c


BRACKETS = [b"{}", b"()", b"[]"]


class Reducer(object):
    def __init__(self, initial, predicate, debug):
        assert isinstance(initial, bytes)
        self.current = initial
        self.__predicate = predicate
        self.__cache = {}
        self.__debug = debug

        self.__exploration_queue = []

        result = predicate(initial)
        if not result:
            raise ValueError("Initial value does not satisfy predicate")
        self.__cache[cache_key(initial)] = result

    def debug(self, *args, **kwargs):
        """Equivalent to print if debugging is enabled, otherwise a no-op."""
        if self.__debug:
            print(*args, **kwargs)

    def predicate(self, value):
        """Cached version of the reduction predicate. Updates
        self.current if the result is True and this would be a shrink."""
        key = cache_key(value)
        try:
            return self.__cache[key]
        except KeyError:
            pass
        result = self.__predicate(value)
        if result:
            if sort_key(value) < sort_key(self.current):
                self.debug(
                    f'Shrink from {len(self.current)} to {len(value)} bytes {"%.2f" % (100.0 * (len(self.current) - len(value)) / len(self.current))}%'
                )
                self.current = value
            else:
                self.debug(
                    f"Found non-shrinking example of length {len(value)} (current best: {len(self.current)})"
                )
        self.__cache[key] = result
        return result

    def attempt(self, value):
        """Tries value as a possible shrink and returns whether it succeeded."""
        return sort_key(value) < sort_key(self.current) and self.predicate(value)

    def attempt_delete_many_sets(self, sets):
        """Attempts to delete each of a set of indices, properly accounting for
        the results of deleting multiple. Will attempt to adapt and deal well with
        doing this faster than linearly where possible, but currently doesn't
        do a very good job of that.
        """
        sets = list(map(frozenset, sets))
        sets.sort(key=lambda s: (len(s), sorted(s, reverse=True)), reverse=True)

        target = self.current

        retained = set(range(len(target)))

        def try_remove(i, j):
            if j > len(sets):
                return False
            nonlocal retained
            to_remove = set()
            for k in range(i, j):
                to_remove |= sets[k]
            if to_remove.isdisjoint(retained):
                return True
            result = self.predicate(
                bytes(
                    [
                        c
                        for i, c in enumerate(target)
                        if i in retained and i not in to_remove
                    ]
                )
            )
            if result:
                retained -= to_remove
            return result

        if try_remove(0, len(sets)):
            return True

        i = 0
        while i < len(sets):
            k = sequences.find_integer(lambda t: try_remove(i, i + t))
            i += k + 1

    def find_paired_brackets(self, bracket, target=None):
        """Returns all pairs of indices corresponding to balanced bracket
        pairs."""
        if target is None:
            target = self.current
        left, right = bracket
        results = []
        stack = []
        for i, c in enumerate(target):
            if c == left:
                stack.append(i)
            elif c == right:
                if stack:
                    results.append((stack.pop(), i))
        return results

    def reduce_by_all_delimiters(self):
        """Performs a series of linear transformations that tries to
        delete elements of the target treating it as a sequence delimited
        by each possible byte as a delimiter."""

        delimiters = set(self.current)
        while delimiters:
            counts = Counter(self.current)
            b = min(delimiters, key=lambda c: (counts[c], c))
            self.reduce_by_delimiter(b)
            delimiters.remove(b)

    def kill_strings(self):
        """Attempts to replace string literals with empty strings."""
        for c in [b"'", b'"']:
            self.debug(f"Killing {repr(c)} delimited strings")
            indices = [i for i, b in enumerate(self.current) if b == c[0]]
            self.attempt_delete_many_sets(
                [range(i + 1, j) for i, j in zip(indices, indices[1:])]
            )

    def delete_bracket_contents(self):
        """Tries deleting the contents of matching brackets. Mainly useful
        for removing redundant and useless control flow in C-like languages,
        but seems surprisingly effective in general."""
        for brackets in BRACKETS:
            self.debug(f"Deleting bracket contents {brackets}")
            self.attempt_delete_many_sets(
                [range(i + 1, j) for i, j in self.find_paired_brackets(brackets)]
            )
            self.reduce_by_delimiter(brackets[0])

    def normalize_whitespace(self):
        """Attempts to normalize and get rid of whitespace in the target."""
        self.remove_byte(b"\r")
        self.debug("Normalizing whitespace")
        self.predicate(re.sub(re.compile(rb"^\s+", re.MULTILINE), b"", self.current))
        self.predicate(re.sub(re.compile(rb"\s+$", re.MULTILINE), b"", self.current))
        while self.attempt(self.current.replace(b"\n\n", b"\n")):
            pass

    def debracket(self):
        """Attempts to remove brackets from expressions, e.g. replacing
        "(a + b)" with "a + b". This is mainly useful for unlocking other
        reductions as it frees us from having to try to keep the brackets
        balanced."""
        for b in BRACKETS:
            self.debug(f"Removing {b} brackets")
            self.attempt_delete_many_sets(self.find_paired_brackets(b))

    def pull_out_braces(self):
        """Attempts to move the contents of braces outside the brace,
        by replacing "foo{ .. }" with "foo; ...". Mostly works well
        for C-like languages."""
        self.debug("Attempt to replace braces with semicolons")

        braces = self.find_paired_brackets(b"{}")
        i = 0
        while i < len(braces):
            u, v = braces[i]
            attempt = bytearray(self.current)
            attempt[u] = b";"[0]
            del attempt[v]
            attempt = bytes(attempt)
            assert attempt != self.current
            if self.predicate(bytes(attempt)):
                self.attempt(re.sub(b";\s*;", b"", self.current))
                self.attempt(re.sub(b"\{\s+\}", b"", self.current))
                braces = self.find_paired_brackets(b"{}")
            else:
                i += 1

    def prefix_lines(self):
        """For each line attempts to replace it with a prefix of it.
        Takes a slightly relaxed notion of line allowing it to be ended
        either by a semicolon or a newline."""
        for terminator in [b"\n", b";"]:
            self.debug(f"Taking prefixes terminated by {terminator}")
            try:
                i = self.current.index(b" ")
            except ValueError:
                return
            while i < len(self.current):
                try:
                    line_end = self.current.index(terminator, i + 1)
                except ValueError:
                    line_end = len(self.current)
                self.attempt(self.current[:i] + self.current[line_end:])
                try:
                    i = self.current.index(b" ", i + 1)
                except ValueError:
                    break

    def strip_re(self, expr):
        """Attempts to remove all regions matching some regular expression."""
        self.attempt_delete_many_sets(
            range(m.start(), m.end()) for m in re.compile(expr).finditer(self.current)
        )

    def remove_comments(self):
        """Attempts to remove various comment like entities from a source file."""
        self.strip_re(rb"(#|//)[^\n]+\n")
        self.strip_re(rb"/\*.+\*/")

    def attempt_typedef_substitutions(self):
        """Hyper-specific reduction pass that really only applies to C and C++.
        Looks for typedefs and attempts to replace their use with their definition.
        Often this is not a win in terms of size for individual substitutions, but
        by removing the typedefs we often win in aggregate. More importantly this can
        unlock other reductions.
        """
        pumped = self.current

        attempted = set()
        while True:
            for typedef in re.compile(br"typedef\s+(.+)\s+(\w+)\s*;").finditer(pumped):
                td = typedef.group(0)
                if td in attempted:
                    continue
                attempted.add(td)
                removed = pumped[: typedef.start()] + pumped[typedef.end() :]
                if self.predicate(removed):
                    pumped = removed
                    break
                name = typedef.group(2)
                definition = typedef.group(1)
                self.debug(f"Attempting to use typedef {name} as {definition}")
                name_re = re.compile(rb"\b" + name + rb"\b")
                fully = name_re.sub(definition, removed)
                if self.predicate(fully):
                    pumped = fully
                else:
                    i = 0
                    targets = list(name_re.finditer(pumped))
                    while i < len(targets):
                        m = targets[i]
                        attempt = pumped[: m.start()] + definition + pumped[m.end() :]
                        if self.predicate(attempt):
                            pumped = attempt
                            targets = list(name_re.finditer(pumped))
                        else:
                            i += 1
                break
            else:
                break

        for typedef in reversed(
            list(re.compile(br"typedef\s+(.+)\s+(\w+)\s*;").finditer(pumped))
        ):
            self.debug(f"Attempting to remove {typedef.group(0)}")
            attempt = pumped[: typedef.start()] + pumped[typedef.end() :]
            if self.predicate(attempt):
                pumped = attempt

    def reduce_c_like_language(self):
        """A collection of passes that are good for dealing with "bracey"
        languages, typically C-descended ones."""
        prev = None
        while prev is not self.current:
            prev = self.current
            self.remove_comments()
            self.normalize_whitespace()
            self.delete_bracket_contents()
            self.reduce_by_delimiter(b";")
            self.reduce_by_delimiter(b"\n")
            self.pull_out_braces()
            self.debracket()
            self.kill_strings()
            self.attempt(self.current.replace(b"\n;", b";"))
            self.attempt_typedef_substitutions()
            if prev is not self.current:
                continue
            self.reduce_by_delimiter(b" ")
            self.normalize_identifiers()
            self.prefix_lines()

    def reduce_by_bytes(self):
        sequences.linear_reduce(
            list(self.current), lambda ls: self.predicate(bytes(ls))
        )

    def remove_byte(self, c):
        """Attempt to remove all instances of a particular byte."""
        self.debug(f"Removing {to_bs(c)}")
        c = to_bs(c)
        return self.attempt(self.current.replace(c, b""))

    def reduce_by_delimiter(self, delimiter):
        """Considering self.current as a sequence delimited by a particular byte,
        try reducing it as that sequence."""

        prev = self.current
        delimiter = to_bs(delimiter)
        self.debug(f"reduce_by_delimiter({delimiter})")

        # First check if we can just remove all of the empty parts in the sequence.
        parts = self.current.split(delimiter)

        if self.attempt(b"".join(parts)):
            delimiter = b""

        # Now apply the sequence reducer.
        if self.attempt(delimiter.join(filter(None, parts))):
            parts = self.current.split(delimiter)
        parts.reverse()
        sequences.linear_reduce(
            parts, lambda ls: self.predicate(delimiter.join(reversed(ls)))
        )
        return prev is not self.current

    def normalize_identifiers(self):
        """Looks for ascii identifiers in the source file that appear more than
        once and attempts to use them as a guide to reduction."""
        identifier = re.compile(rb"\b[A-Za-z_]\w+\b")

        positions = defaultdict(list)

        for m in identifier.finditer(self.current):
            positions[m.group(0)].append(m.start)

        identifiers = []

        for k in positions:
            if len(positions[k]) > 1:
                identifiers.append(k)

        identifiers.sort(key=lambda t: len(t) * len(positions[t]))

        for s in identifiers:
            self.debug(f"Normalizing {s}")
            parts = self.current.split(s)
            if self.predicate(b"".join(parts)):
                delimiter = b""
            else:
                delimiter = s
                delimiter = bytes(
                    sequences.linear_reduce(
                        s, lambda q: self.predicate(bytes(q).join(parts))
                    )
                )
            self.debug(f"Reducing split on {s}")
            sequences.linear_reduce(
                parts, lambda ls: self.predicate(delimiter.join(ls))
            )

    def reduce(self):
        """Run all reduction passes to a fixed point."""
        prev = None
        while prev is not self.current:
            prev = self.current
            self.reduce_c_like_language()
            self.reduce_by_all_delimiters()
            self.reduce_by_bytes()
