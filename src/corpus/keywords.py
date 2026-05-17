"""
Tradition validation keywords — used by corpus validator to detect wrong source downloads.
Check the first ~2000 chars of downloaded passages for these keywords (case-insensitive).
If none match, the file is flagged SUSPICIOUS (likely a wrong Project Gutenberg ID).
"""

TRADITION_KEYWORDS: dict[str, list[str]] = {
    "advaita_vedanta": [
        "brahman", "atman", "upanishad", "vedanta", "maya", "vedas",
        "brahma", "om ", "moksha", "samadhi",
    ],
    "bhakti_hinduism": [
        "krishna", "vishnu", "arjuna", "bhagavad", "gita", "avatar",
        "bhakti", "devotion", "dharma", "karma",
    ],
    "buddhism": [
        "buddha", "dharma", "nirvana", "suffering", "dhamma", "bodhi",
        "karma", "enlightenment", "sangha", "monk",
    ],
    "daoism": [
        "tao ", "dao ", " tao", " dao", "yang", "yin",
        "lao tzu", "laozi", "zhuangzi", "wu wei", "te ",
    ],
    "greek": [
        "zeus", "hesiod", "olymp", "theogony", "apollo", "hermes",
        "prometheus", "muse", "titan", "kronos",
    ],
    "norse": [
        "odin", "thor", "yggdrasil", "valhalla", "asgard", "ragnar",
        "baldur", "loki", "frigg", "norns",
    ],
    "shinto": [
        "kami", "izanagi", "izanami", "amaterasu", "mikoto", "musubi",
        "japan", "shinto", "shrine", "susanoo",
    ],
    "egyptian": [
        "osiris", "isis", "ra ", "pharaoh", "anubis", "horus",
        "book of the dead", "egypt", "atum", "nile",
    ],
    "gnosticism": [
        "sophia", "demiurge", "pleroma", "gnosis", "aeon", "barbelo",
        "nag hammadi", "archon", "logos", "gnostic",
    ],
    "lovecraft": [
        "cthulhu", "lovecraft", "elder", "arkham", "miskatonic", "shoggoth",
        "necronomicon", "tentacle", "ancient ones", "eldritch",
    ],
    "aztec": [
        "aztec", "mexico", "quetzal", "maya", "nahua", "popol vuh",
        "tlaloc", "coatl", "tenochtitlan", "mexico",
    ],
    "pantheism": [
        "spinoza", "substance", "god or nature", "natura", "attribute",
        "mode ", "ethics", "proposition", "deus sive natura",
    ],
    "absurdism": [
        "nietzsche", "zarathustra", "hume", "lucretius", "epicurus",
        "will to power", "eternal return", "atoms", "causation",
    ],
}
