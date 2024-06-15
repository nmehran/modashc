from methods.sources import depth_first_sort_sources


# Comprehensive Test Case
sources = {
    '/project/main.sh': [
        '/project/env.sh',
        '/project/utils.sh',
        '/project/logging.sh',
        '/project/wg_ops.sh'
    ],
    '/project/env.sh': [
        '/project/config.sh',
    ],
    '/project/config.sh': [
        '/project/constants.sh',
    ],
    '/project/constants.sh': [],
    '/project/utils.sh': [
        '/project/helpers.sh',
        '/project/constants.sh',  # Intentional reuse of a previously listed file
    ],
    '/project/helpers.sh': [],
    '/project/logging.sh': [],
    '/project/wg_ops.sh': [
        '/project/wg_config.sh',
        '/project/constants.sh',  # Intentional reuse of a previously listed file
    ],
    '/project/wg_config.sh': [
        '/project/wg_helpers.sh',
    ],
    '/project/wg_helpers.sh': [
        '/project/logging.sh',  # Intentional cross dependency
    ],
    '/project/circular.sh': [
        '/project/circular_dep.sh',
    ],
    '/project/circular_dep.sh': [
        '/project/circular.sh',  # Circular dependency
    ],
}

entry_point = '/project/main.sh'

# Expected output should show each file with its dependencies correctly ordered before it.
expected_order = [
    '/project/constants.sh',
    '/project/config.sh',
    '/project/env.sh',
    '/project/helpers.sh',
    '/project/utils.sh',
    '/project/logging.sh',
    '/project/wg_helpers.sh',
    '/project/wg_config.sh',
    '/project/wg_ops.sh',
    '/project/main.sh'
]

# Run the depth-first sort
ordered_sources = depth_first_sort_sources(sources, entry_point)

# Assertions
assert ordered_sources == expected_order, f"Expected {expected_order}, but got {ordered_sources}"
ordered_sources
