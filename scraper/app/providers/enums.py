from enum import Enum


class ProviderKey(Enum):
    _24UR = "24ur"
    RTV = "rtv"
    DELO = "delo"
    SIOL = "siol"
    NOVA24TV = "nova24tv"
    NECENZURIRANO = "necenzurirano"
    DNEVNIK = "dnevnik"
    SVET24 = "svet24"
    VECER = "vecer"
    MLADINA = "mladina"
    PRIMORSKENOVICE = "primorskenovice"
    LJUBLJANSKENOVICE = "ljubljanskenovice"
    MARIBOR24 = "maribor24"
    SLOTECH = "slotech"
    REPORTER = "reporter"
    N1INFO = "n1info"
    ZURNAL24 = "zurnal24"
    SLOVENSKENOVICE = "slovenskenovice"
    STA = "sta"
    CEKIN = "cekin"
    DEMOKRACIJA = "demokracija"
    BLOOMBERGADRIA = "bloombergadria"
    INFO360 = "info360"
    LOKALEC = "lokalec"
    DOMOVINA = "domovina"


# bias ratings are based on the following research:
# https://www.frontiersin.org/journals/communication/articles/10.3389/fcomm.2023.1143786/full
# https://www.eecs.qmul.ac.uk/~mpurver/papers/caporusso-et-al24jadt-politics.pdf
class BiasRating(Enum):
    LEFT = "left"
    CENTER_LEFT = "center-left"
    CENTER = "center"
    CENTER_RIGHT = "center-right"
    RIGHT = "right"
