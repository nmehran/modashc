import os.path

from methods.sources import get_sources

# Example usage
entry_point = os.path.abspath("./sources/main.sh")
sources_info = get_sources(entry_point)
print(sources_info)
