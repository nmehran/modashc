import argparse
from methods.compile import compile_sources


def main(entry_point, output_file, mode="context"):
    compile_sources(entry_point, output_file, mode=mode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Merge Bash scripts into a single script.')
    parser.add_argument('entrypoint', type=str, help='The entry-point Bash script that initiates the merging process.')
    parser.add_argument('output', type=str, help='The output file where the merged script will be saved.')
    parser.add_argument(
        '--mode',
        choices=('context', 'executable'),
        default='context',
        help='Output mode. context is readable-first; executable preserves Bash source execution behavior.',
    )
    args = parser.parse_args()
    main(entry_point=args.entrypoint, output_file=args.output, mode=args.mode)
