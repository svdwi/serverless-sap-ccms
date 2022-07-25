import logging
from enum import Enum
import json

from pprint import pprint
from pydantic import BaseModel

import boto3

from pyrfc import Connection


SECRET_NAME = "test/ccms_lambda"

SAP_SID = "ABA"
EXT_COMPANY = "DUMMY"
EXT_PRODUCT = "DUMMY"
EXT_USER_NAME = "DUMMY"

SAP_INTERFACE = "XAL"
SAP_INTERFACE_VERSION = "1.0"
TRACE_LEVEL = "0"

logger = logging.getLogger(__name__)


class SapCredential(BaseModel):
    ashost: str
    sysnr: str
    client: str
    user: str
    passwd: str
    trace: str = TRACE_LEVEL


class MteType(Enum):
    PERFORMANCE = "100"
    LOG = "101"
    STATUS = "102"
    TEXT = "111"


class BapiError(Exception):
    pass


class Mte(BaseModel):
    context_name: str
    object_name: str
    mte_name: str


class CcmsBapiCaller:
    def __init__(self, conn: Connection):
        self._conn = conn

    def _call_ccms_bapi(
        self, bapi_name: str, tid: dict, external_user_name: str
    ) -> dict:
        res = self._conn.call(
            bapi_name,
            EXTERNAL_USER_NAME=external_user_name,
            TID=tid,
        )
        if res["RETURN"]["TYPE"] == "E":
            logger.error(res["RETURN"]["MESSAGE"])
            raise BapiError(f"BAPI Error -> {res}")
        return res

    def _get_tid_by_name(
        self,
        sid: str,
        mte: Mte,
        external_user_name: str,
    ) -> dict:
        res = self._conn.call(
            "BAPI_SYSTEM_MTE_GETTIDBYNAME",
            SYSTEM_ID=sid,
            CONTEXT_NAME=mte.context_name,
            OBJECT_NAME=mte.object_name,
            MTE_NAME=mte.mte_name,
            EXTERNAL_USER_NAME=external_user_name,
        )
        if res["RETURN"]["TYPE"] == "E":
            logger.error(res["RETURN"]["MESSAGE"])
            raise BapiError(f"BAPI Error -> {res}")
        return res["TID"]

    def logon_xmi_interface(self, company: str, product: str, name: str, version: str):
        res = self._conn.call(
            "BAPI_XMI_LOGON",
            EXTCOMPANY=company,
            EXTPRODUCT=product,
            INTERFACE=name,
            VERSION=version,
        )
        if res["RETURN"]["TYPE"] == "E":
            logger.error(res["RETURN"]["MESSAGE"])
            raise BapiError(f"BAPI Error -> {res}")

    def logoff_xmi_interface(self, name: str):
        res = self._conn.call(
            "BAPI_XMI_LOGOFF",
            INTERFACE=name,
        )
        if res["RETURN"]["TYPE"] == "E":
            logger.error(res["RETURN"]["MESSAGE"])
            raise BapiError(f"BAPI Error -> {res}")

    def get_ccms_data(self, sid: str, mte: Mte, external_user_name: str):
        tid = self._get_tid_by_name(
            sid=sid, mte=mte, external_user_name=external_user_name
        )
        mt_class = tid["MTCLASS"]

        if mt_class == MteType.PERFORMANCE.value:
            res = self._call_ccms_bapi(
                bapi_name="BAPI_SYSTEM_MTE_GETPERFCURVAL",
                tid=tid,
                external_user_name=external_user_name,
            )
            return res["CURRENT_VALUE"]["ALRELEVVAL"]
        elif mt_class == MteType.LOG.value:
            res = self._call_ccms_bapi(
                bapi_name="BAPI_SYSTEM_MTE_GETMLCURVAL",
                tid=tid,
                external_user_name=external_user_name,
            )
            return res["XMI_MSG_EXT"]
        elif mt_class == MteType.STATUS.value:
            res = self._call_ccms_bapi(
                bapi_name="BAPI_SYSTEM_MTE_GETSMVALUE",
                tid=tid,
                external_user_name=external_user_name,
            )
            return res["VALUE"]
        elif mt_class == MteType.TEXT.value:
            res = self._call_ccms_bapi(
                bapi_name="BAPI_SYSTEM_MTE_GETTXTPROP",
                tid=tid,
                external_user_name=external_user_name,
            )
            return res["PROPERTIES"]["TEXT"]
        else:
            raise NotImplementedError(f"MTCLASS -> {mt_class}")


def handler(event, context=None):
    # eventから監視対象のMTEを取得
    mte = Mte.parse_obj(event)

    # 監視対象インスタンスへの接続情報を取得
    secrets = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_NAME)
    sap_cred = SapCredential.parse_obj(json.loads(secrets["SecretString"]))
    print(sap_cred)
    conn = Connection(**sap_cred.dict())
    bapi = CcmsBapiCaller(conn=conn)

    try:
        bapi.logon_xmi_interface(
            company=EXT_COMPANY,
            product=EXT_PRODUCT,
            name=SAP_INTERFACE,
            version=SAP_INTERFACE_VERSION,
        )
        current_val = bapi.get_ccms_data(
            sid=SAP_SID, mte=mte, external_user_name=EXT_USER_NAME
        )
        logger.info(f"MTE-> {mte}, VALUE-> {current_val}")
    except Exception as e:
        logger.error(e)
    finally:
        bapi.logoff_xmi_interface(name=SAP_INTERFACE)


if __name__ == "__main__":
    events = [
        # PERF
        {
            "context_name": "vhcalabaci_ABA_00",
            "object_name": "Dialog",
            "mte_name": "ResponseTimeDialog",
        },
        # STATUS
        # {
        #    "context_name": "vhcalabaci_ABA_00",
        #    "object_name": "R3Abap",
        #    "mte_name": "Shortdumps",
        # },
        #
        {
            "context_name": "vhcalabaci_ABA_00",
            "object_name": "InstanceAsTask",
            "mte_name": "Log",
        },
        # TEXT
        # {
        #    "context_name": "vhcalabaci_ABA_00",
        #    "object_name": "Server Configuration",
        #    "mte_name": "Machine Type",
        # },
    ]
    for e in events:
        handler(event=e)
