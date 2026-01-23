from app.providers.news_provider import NewsProvider

from app.providers._24ur import _24URProvider
from app.providers.rtv import RTVProvider
from app.providers.delo import DeloProvider
from app.providers.siol import SiolProvider
from app.providers.nova24tv import Nova24TVProvider
from app.providers.necenzurirano import NecenzuriranoProvider
from app.providers.dnevnik import DnevnikProvider
from app.providers.svet24 import Svet24Provider
from app.providers.vecer import VecerProvider
from app.providers.mladina import MladinaProvider
from app.providers.primorskenovice import PrimorskeNoviceProvider
from app.providers.ljubljanskenovice import LjNoviceProvider
from app.providers.maribor24 import Maribor24Provider
from app.providers.slotech import SloTechProvider
from app.providers.reporter import ReporterProvider
from app.providers.n1info import N1InfoProvider
from app.providers.zurnal24 import Zurnal24Provider
from app.providers.slovenskenovice import SlovenskeNoviceProvider
from app.providers.sta import STAProvider
from app.providers.cekin import CekinProvider
from app.providers.demokracija import DemokracijaProvider
from app.providers.bloombergadria import BloombergAdriaProvider
from app.providers.info360 import Info360Provider
from app.providers.lokalec import LokalecProvider
from app.providers.domovina import DomovinaProvider
from app.providers.zanimame import ZanimaMeProvider
from app.providers.finance import FinanceProvider


PROVIDERS: list[NewsProvider] = [
    _24URProvider(),
    RTVProvider(),
    DeloProvider(),
    SiolProvider(),
    Nova24TVProvider(),
    NecenzuriranoProvider(),
    DnevnikProvider(),
    Svet24Provider(),
    VecerProvider(),
    MladinaProvider(),
    PrimorskeNoviceProvider(),
    LjNoviceProvider(),
    Maribor24Provider(),
    SloTechProvider(),
    ReporterProvider(),
    N1InfoProvider(),
    Zurnal24Provider(),
    SlovenskeNoviceProvider(),
    STAProvider(),
    CekinProvider(),
    DemokracijaProvider(),
    BloombergAdriaProvider(),
    Info360Provider(),
    LokalecProvider(),
    DomovinaProvider(),
    ZanimaMeProvider(),
    FinanceProvider(),
]
