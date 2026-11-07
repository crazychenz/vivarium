ADJECTIVES = (
    "amber", "ancient", "bold", "brave", "bright", "brisk", "calm", "careful",
    "clever", "cosy", "curious", "daring", "eager", "elegant", "faithful",
    "fancy", "fearless", "fluffy", "gentle", "glad", "golden", "graceful",
    "happy", "hardy", "honest", "humble", "jolly", "keen", "kind", "lively",
    "lucky", "mellow", "merry", "mighty", "modest", "nimble", "noble", "patient",
    "plucky", "polite", "proud", "quiet", "rapid", "restless", "rustic",
    "serene", "shiny", "silent", "sleepy", "snug", "steady", "sturdy", "sunny",
    "swift", "tidy", "tranquil", "vivid", "warm", "wild", "wise", "witty",
    "zesty",
)
 
NOUNS = (
    "acorn", "anchor", "badger", "beacon", "birch", "bramble", "breeze",
    "bridge", "canyon", "cedar", "clover", "comet", "compass", "coral",
    "cricket", "dolphin", "dragonfly", "driftwood", "ember", "falcon", "fern",
    "ferry", "firefly", "fjord", "forest", "galaxy", "garden", "glacier",
    "goose", "harbor", "hawk", "heron", "hedgehog", "horizon", "iceberg",
    "island", "jasmine", "kettle", "kestrel", "lagoon", "lantern", "lark",
    "lighthouse", "lily", "lynx", "maple", "marble", "meadow", "meteor",
    "moss", "narwhal", "nebula", "oak", "orchid", "otter", "owl", "panda",
    "pebble", "pine", "puffin", "quartz", "rabbit", "raven", "reef", "river",
    "robin", "saddle", "sparrow", "squirrel", "summit", "swan", "thistle",
    "thunder", "tulip", "tundra", "valley", "violin", "walnut", "waterfall",
    "willow", "wolf", "wren", "yarrow", "zephyr",
)

def generate_path(prefix_path) -> str:
 
    import random
    for _ in range(len(NOUNS) * len(ADJECTIVES)):
        try:
            result_path = prefix_path / f"{random.choice(ADJECTIVES)}_{random.choice(NOUNS)}"
            result_path.mkdir(parents=True)
            return result_path
        except:
            continue
 
    raise Exception("Failed to generate prefix path.")