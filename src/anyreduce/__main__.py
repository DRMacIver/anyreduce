import click
import subprocess
import shlex
from anyreduce.reducer import Reducer
import traceback


@click.command()
@click.argument("inputfile")
@click.argument("testcommand")
@click.option("--timeout", default=1.0)
@click.option("--debug/--no-debug", default=False)
def main(inputfile, testcommand, timeout, debug):
    testcommand = shlex.split(testcommand)

    with open(inputfile, "rb") as i:
        initial = i.read()

    def predicate(b):
        try:
            result = (
                subprocess.run(
                    testcommand,
                    input=b,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                ).returncode
                == 0
            )
            if result:
                with open(inputfile + ".reduced", "wb") as o:
                    o.write(b)
            return result
        except subprocess.TimeoutExpired:
            return False

    reducer = Reducer(initial, predicate, debug=debug)
    try:
        reducer.reduce()
    except KeyboardInterrupt:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
