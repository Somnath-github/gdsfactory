"""
Some manhattan routes have disconnected waveguides

"""

import pp


if __name__ == "__main__":
    c = pp.Component()
    c1 = c << pp.c.array(pitch=100)
    c2 = c << pp.c.array(pitch=5)

    c2.movex(200)
    c1.y = 0
    c2.y = 0

    routes = pp.routing.get_bundle_path_length_match(
        c1.get_ports_list(orientation=0),
        c2.get_ports_list(orientation=180),
        end_straight_offset=0,
        start_straight=0,
        separation=50,
        # modify_segment_i=-3,
        waveguide="nitride",
        radius=10
        # radius=5  # smaller radius works
    )

    for route in routes:
        c.add(route.references)

    c.show()
