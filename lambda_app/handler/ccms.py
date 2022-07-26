import os
import logging
from enum import Enum
import json


import boto3
from pydantic import BaseModel
from pyrfc import Connection


SAP_INTERFACE = "XAL"
SAP_INTERFACE_VERSION = "1.0"

EXT_COMPANY = os.getenv("EXT_COMPANY")
EXT_PRODUCT = os.getenv("EXT_PRODUCT")
EXTERNAL_USER_NAME = os.getenv("EXTERNAL_USER_NAME")
TRACE_LEVEL = os.getenv("TRACE_LEVEL")
SECRET_NAME = os.getenv("SECRET_NAME")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SapConnectionSecret(BaseModel):
    sid: str
    ashost: str
    sysnr: str
    client: str
    user: str
    passwd: str


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


def get_sap_connection(sap_secret: SapConnectionSecret) -> Connection:
    return Connection(
        ashost=sap_secret.ashost,
        sysnr=sap_secret.sysnr,
        client=sap_secret.client,
        user=sap_secret.user,
        passwd=sap_secret.passwd,
    )


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
    logger.info(f"start event -> {event}")
    mte = Mte.parse_obj(event)
    logger.info(f"target MTE -> {mte}")

    secrets = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_NAME)
    sap_secret = SapConnectionSecret.parse_obj(json.loads(secrets["SecretString"]))

    # 監視対象インスタンスへの接続情報を取得
    bapi = CcmsBapiCaller(conn=get_sap_connection(sap_secret=sap_secret))

    try:
        bapi.logon_xmi_interface(
            company=EXT_COMPANY,
            product=EXT_PRODUCT,
            name=SAP_INTERFACE,
            version=SAP_INTERFACE_VERSION,
        )
        current_val = bapi.get_ccms_data(
            sid=sap_secret.sid, mte=mte, external_user_name=EXTERNAL_USER_NAME
        )
        logger.info(f"MTE-> {mte}, VALUE-> {current_val}")
        logger.info("completed")
    except Exception as e:
        logger.error(e)
    finally:
        bapi.logoff_xmi_interface(name=SAP_INTERFACE)
