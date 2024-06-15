import argparse
from methods.compile import compile_sources


def main(entry_point, output_file):
    compile_sources(entry_point, output_file)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Merge Bash scripts into a single script.')
    parser.add_argument('entrypoint', type=str, help='The entry-point Bash script that initiates the merging process.')
    parser.add_argument('output', type=str, help='The output file where the merged script will be saved.')
    args = parser.parse_args()
    main(entry_point=args.entrypoint, output_file=args.output)
