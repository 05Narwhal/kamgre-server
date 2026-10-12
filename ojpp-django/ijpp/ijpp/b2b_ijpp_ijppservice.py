from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional
from xml.etree.ElementTree import QName
from xsdata.models.datatype import XmlDateTime


@dataclass
class ActivationSAMRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sSAMSerialNumber: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sTerminalSerialNumber: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ActivationSAMResponse_1:
    class Meta:
        name = "ActivationSAMResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSAMAuthetnticationKey: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Card:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtBlacklistedTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtInitDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtLastStatusChangeDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtPersonificationDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtValidToDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iBlacklisted: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iBlacklistedChangeReasonId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iCardType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iPId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CasovniFaktor:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    casDo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    casOd: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    faktor: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idCasovniFaktor: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idCasovniRezim: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    naziv: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    opis: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CatalogData:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"


@dataclass
class CheckActivationCodeRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lActivationCode: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CheckActivationCodeResponse_1:
    class Meta:
        name = "CheckActivationCodeResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckCardOnSoftBlackListRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CheckCardOnSoftBlackListResponse_1:
    class Meta:
        name = "CheckCardOnSoftBlackListResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iExistOnList: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ConditionalProduct:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTariffClassId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffProductId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CreateIdentificationCodeRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CreateIdentificationCodeResponse_1:
    class Meta:
        name = "CreateIdentificationCodeResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sIdentificationCode: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DelExecutableListResponse_1:
    class Meta:
        name = "DelExecutableListResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DelExecutableList_1:
    class Meta:
        name = "DelExecutableList"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iAction: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ExeCardFailedObject:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    sDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ExeCardObject:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"


@dataclass
class Geometrija:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    X: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    Y: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetAppKeysRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetAppKeysResponse_1:
    class Meta:
        name = "GetAppKeysResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sCommKey: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sPackageKey: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetBlackListRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iLastBlackListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iReceiveBlockListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iReceiveBlockNumber: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iReceiveBlockSize: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetCUIDsByIdentityNumberRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    IdentityNumber: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardPassengerStatusRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetCardProductsRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetCardRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetCardStatusRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetCardStatusResponse_1:
    class Meta:
        name = "GetCardStatusResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iCardStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetDuplicateDataRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetExecutableListRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iCompactType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iExeListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iReceiveBlockListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iReceiveBlockNumber: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iReceiveBlockSize: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPCatalogsRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iCatalogType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iQueryType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPDateTimeRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetIJPPDateTimeResponse_1:
    class Meta:
        name = "GetIJPPDateTimeResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtIJPPDateTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetNearestStationaRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    HsMid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetPassengerRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtBirthDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sAddress: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sFirstName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sIdentityNumber: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sLastName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPosRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iPosId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetPostajneTockeZaPrevoznikaRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPrevoznik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetStationsListRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetSubTransactionsBySubsidyRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtDateFrom: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtDateUntil: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iCompanyId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sSubsidyId: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetSubTransactionsRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtDateFrom: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtDateUntil: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iCompanyId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lLastTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffTypeTransitionMatrixRequest:
    class Meta:
        name = "GetTariffClassTransitionMatrixRequest"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetTerminalRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetTransactionsRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtDateFrom: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtDateUntil: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iCompanyId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iReturnMode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lLastTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediIndexZaPrevoznikaRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPrevoznik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetWhiteListRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    bIncremental: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iReceiveBlockSize: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lLastWLVersion: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class IdentifyTransactionParametersRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class Location:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sLocationName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class LocationTransitionMatrix:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iLocationIdFrom: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iLocationIdTo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iNumberOfTransitions: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class Lokacija:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idLokacija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    ime: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    tipLokacije: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class Passenger:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtBirthDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iZip: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sAddress: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sCity: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sCountry: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sEmail: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sFirstName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sIdentityNumber: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sLastName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sMSISDN: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Pos:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dLatitude: Optional['Decimal'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dLongitude: Optional['Decimal'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iCompanyId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iPosId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sAddress: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sCity: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sCountry: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sEmail: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sPhone: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSubBusOperatorCode: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSubPassword: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSubUserName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sZIP: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Prestop:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPostajalisceDo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPostajalisceOd: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPrestop: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPrestopnaTocka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    intervalPrestopanja: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    opomba: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class PrestopnaTocka:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPrestopnaTocka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    ime: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    opomba: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    oznaka: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Prevoznik:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    FareURL: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    TRR: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    TRRPriBanki: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    URL: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    davcnaStevilka: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    email: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPrevoznik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    ime: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    kontaktnaOseba: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    kooperant: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    maticnaStevilka: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    naslov: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    oznakaPrevoznika: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    telefon: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ProductPriceIn:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iProductId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffClassId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTicketStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class ProductPriceOut:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    fPriceValue: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class RegistrationTerminalRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    sSerialNumber: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Relacija:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPostajalisceDo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPostajalisceOd: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idRelacija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class ResultMessage:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    ResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    ResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class RezimInterval:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    akcija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    danDo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    danOd: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idRezim: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idRezimInterval: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mesecDo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mesecOd: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    ponedeljek: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    torek: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sreda: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    cetrtek: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    petek: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sobota: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    nedelja: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    praznik: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class RezimTermin:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    akcija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idRezim: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idRezimTermin: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    termin: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SSLCertificate:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    bSSLCertFileContent: Optional['bytes'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
            "format": "base64",
        }
    )
    sSSLCertFileName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetBlackListRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iBLCause: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iUserld: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class SetBlackListResponse_1:
    class Meta:
        name = "SetBlackListResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iBlackListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetCardResponse_1:
    class Meta:
        name = "SetCardResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetDelovnaNalogaZaPrevoznikResponse:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetNewCardStatusRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iCardStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iCause: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class SetNewCardStatusResponse_1:
    class Meta:
        name = "SetNewCardStatusResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iOldCardStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPassengerResponse_1:
    class Meta:
        name = "SetPassengerResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iPId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPosResponse_1:
    class Meta:
        name = "SetPosResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iPosId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetTerminalResponse_1:
    class Meta:
        name = "SetTerminalResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SpremeniVeljavnostDelovneNalogeResponse_1:
    class Meta:
        name = "SpremeniVeljavnostDelovneNalogeResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Station:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sObcina: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sOznaka: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sStationName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class StationDetails:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    IsMainStation: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    Latitude: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    Longitude: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    StationCategory: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    StationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    TransportMode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class SubTransaction:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtStartTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtValidFrom: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtValidTo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fPriceValue: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fSubFullPrice: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fSubFullPriceReported: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fSubPayment: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iCompanyId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iDistance: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iEndtStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iOfflineStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPosId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStartStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffClassId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffProductId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTicketStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTransactionType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lRefTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sCompanyCode: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sCompanyDomain: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sPosName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSubsidyId: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SycSubsidiesRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class TariffType:
    class Meta:
        name = "TariffClass"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iKilometersFrom: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iKilometersTo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPriority: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffClassId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iValidityMinutes: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sTariffClassName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class TariffDef:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTariffId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class TariffLocationSubLocations:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iSubLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class TariffPrice:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    fPriceValue: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffClassId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffProductId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffStatusId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class TariffStatus:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTariffStatusId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffStatusType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sTariffStatusName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Terminal:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtProductionDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtSoftwareRevisionDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iMerchantId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iOwnerId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPosId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStatusId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTerminalSubTypeId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTerminalTypeId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sNotes: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSerialNumber: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSoftwareRevision: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSoftwareVersion: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class TransactionExecutionStatus:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Description: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    RefNumberId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    Status: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    TransactionExecutionID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class TransitionMatrix:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTariffClassTransitionsId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class UpdateActivationCodeDateAndStatusRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lActivationCode: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class UpdateActivationCodeDateAndStatusResponse_1:
    class Meta:
        name = "UpdateActivationCodeDateAndStatusResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardPassengerStatusResponse_1:
    class Meta:
        name = "UpdateCardPassengerStatusResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardResponse_1:
    class Meta:
        name = "UpdateCardResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class VozniRed:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"


@dataclass
class Voznja:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"


@dataclass
class VoznjaGrp:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPredhodnaVoznja: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idTip: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznja: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class VoznjaIndex:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idRezim: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznja: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class VoznjaOpis:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    zapStPostajalisca: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class WorkStatus:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtEndTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtStartTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iCompanyId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iWorkStatusId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sWorkStatusName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class wsMessageContext:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lRequestId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sSenderId: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSenderPass: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfbase64Binary:
    class Meta:
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"

    base64Binary: List['bytes'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
            "format": "base64",
        }
    )


@dataclass
class ArrayOfint:
    class Meta:
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"

    int_value: List['int'] = field(
        default_factory=list,
        metadata={
            "name": "int",
            "type": "Element",
        }
    )


@dataclass
class ArrayOflong:
    class Meta:
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"

    long: List['int'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class QName_type:
    class Meta:
        name = "QName"
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['QName'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class anyType:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    any_element: Optional['object'] = field(
        default=None,
        metadata={
            "type": "Wildcard",
            "namespace": "##any",
        }
    )


@dataclass
class anyURI:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['str'] = field(
        default="",
        metadata={
            "nillable": True,
        }
    )


@dataclass
class base64Binary:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['bytes'] = field(
        default=None,
        metadata={
            "nillable": True,
            "format": "base64",
        }
    )


@dataclass
class boolean:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['bool'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class byte:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class char:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class dateTime:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class decimal:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['Decimal'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class double:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['float'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class duration:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['str'] = field(
        default="",
        metadata={
            "min_inclusive": "-P10675199DT2H48M5.4775808S",
            "max_inclusive": "P10675199DT2H48M5.4775807S",
            "pattern": r"\-?P(\d*D)?(T(\d*H)?(\d*M)?(\d*(\.\d*)?S)?)?",
            "nillable": True,
        }
    )


@dataclass
class float_type:
    class Meta:
        name = "float"
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['float'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class guid:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['str'] = field(
        default="",
        metadata={
            "pattern": r"[\da-fA-F]{8}-[\da-fA-F]{4}-[\da-fA-F]{4}-[\da-fA-F]{4}-[\da-fA-F]{12}",
            "nillable": True,
        }
    )


@dataclass
class int_type:
    class Meta:
        name = "int"
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class long:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class short:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class string:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['str'] = field(
        default="",
        metadata={
            "nillable": True,
        }
    )


@dataclass
class unsignedByte:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class unsignedInt:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class unsignedLong:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class unsignedShort:
    class Meta:
        nillable = True
        namespace = "http://schemas.microsoft.com/2003/10/Serialization/"

    value: Optional['int'] = field(
        default=None,
        metadata={
            "nillable": True,
        }
    )


@dataclass
class ArrayOfCasovniFaktor:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    CasovniFaktor: List['CasovniFaktor'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfCatalogData:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    CatalogData: List['CatalogData'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfConditionalProduct:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    ConditionalProduct: List['ConditionalProduct'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfDelExecutableList:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    DelExecutableList: List['DelExecutableList_1'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfExeCardFailedObject:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    ExeCardFailedObject: List['ExeCardFailedObject'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfExeCardObject:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    ExeCardObject: List['ExeCardObject'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfGeometrija:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Geometrija: List['Geometrija'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfLocation:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Location: List['Location'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfLokacija:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Lokacija: List['Lokacija'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfPassenger:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Passenger: List['Passenger'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfPrestop:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Prestop: List['Prestop'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfPrestopnaTocka:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    PrestopnaTocka: List['PrestopnaTocka'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfPrevoznik:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Prevoznik: List['Prevoznik'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfRelacija:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Relacija: List['Relacija'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfRezimInterval:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    RezimInterval: List['RezimInterval'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfRezimTermin:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    RezimTermin: List['RezimTermin'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfSSLCertificate:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    SSLCertificate: List['SSLCertificate'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfStation:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Station: List['Station'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfStationDetails:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    StationDetails: List['StationDetails'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfSubTransaction:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    SubTransaction: List['SubTransaction'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfTariffType:
    class Meta:
        name = "ArrayOfTariffClass"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    TariffClass: List['TariffType'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfTariffDef:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    TariffDef: List['TariffDef'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfTariffLocationSubLocations:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    TariffLocationSubLocations: List['TariffLocationSubLocations'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfTariffPrice:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    TariffPrice: List['TariffPrice'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfTariffStatus:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    TariffStatus: List['TariffStatus'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfTransactionExecutionStatus:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    TransactionExecutionStatus: List['TransactionExecutionStatus'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfTransitionMatrix:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    TransitionMatrix: List['TransitionMatrix'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfVozniRed:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    VozniRed: List['VozniRed'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfVoznjaGrp:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    VoznjaGrp: List['VoznjaGrp'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfVoznjaIndex:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    VoznjaIndex: List['VoznjaIndex'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfWorkStatus:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    WorkStatus: List['WorkStatus'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class BlackList:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iBlackListCRC: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iBlacklistId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCuid: Optional['ArrayOflong'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class BlacklistCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CUID(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CUIDFailed(ExeCardFailedObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CardPassengerStatus(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtTicketStatusEndDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtTicketStatusStartDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTicketStatusFormat: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTicketStatusID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CardPassengerStatusFailed(ExeCardFailedObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CardProductFailed(ExeCardFailedObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CardProductShort(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtEndDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtStartDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CardProductShortFailed(ExeCardFailedObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtEndDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtStartDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CardRelation(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtValidFrom: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtValidTo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iCardRelationIndex: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iDistance: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iEndStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iEndStationLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iFormatIdentifier: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iLineDefinition: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iLineId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iNumberOfStations: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iOnCard: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iOneWay: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iStID: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStartStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iStartStationLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iSubsidy: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iValidStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sEndStationName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sStartStationName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CardRelationFaild(ExeCardFailedObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CardRelationShort(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class CardStatusCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCUIDsByIdentityNumberResponse_1(ResultMessage):
    class Meta:
        name = "GetCUIDsByIdentityNumberResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['ArrayOflong'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardResponse_1:
    class Meta:
        name = "GetCardResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mCardData: Optional['Card'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCasovniRezimiRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idCasovniRezimi: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetConaRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idCone: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLinijskiOdsekiRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iReturnMode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idLinijskiOdseki: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLokacijeRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idLokacije: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPosResponse_1:
    class Meta:
        name = "GetPosResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mPosData: Optional['Pos'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajaliscaRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iReturnMode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajalisca: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iReturnMode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajneTocke: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopiRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPrestopi: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopneTockeRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPrestopneTocke: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrevoznikiRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPrevozniki: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetProductPriceRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mProductPriceIn: Optional['ProductPriceIn'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetProductPriceResponse_1:
    class Meta:
        name = "GetProductPriceResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mProductPriceOut: Optional['ProductPriceOut'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelacijeRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idRelacije: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelationRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iEndStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iInnermediateStations: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStartStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetRezimiRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idRezimi: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiZaPrevoznikaRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPrevoznik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idRezimi: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTariffIds: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class GetTerminalResponse_1:
    class Meta:
        name = "GetTerminalResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mTerminalData: Optional['Terminal'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediZaPrevoznikaRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtVeljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtVeljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPrevoznik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idTipPrevoza: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVozniRed: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznja: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    isExtStructure: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class IJPPTransactionTypeCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTransactionType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class LocationCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class LocationTransitions:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTariffClassTransitionsId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mLocationTransitionMatrixData: Optional['LocationTransitionMatrix'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class OfflineStatusCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iOfflineStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Postajalisce:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    geometrija: Optional['Geometrija'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    glavnoPostajalisce: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idLokacija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idNaselje: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idObcina: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajalisce: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPredhodnik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idTipPostajalisca: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idUpravljavec: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVrstaPostajalisca: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idVrstaPrevoza: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVrstaUpravljavca: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    ime: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    jeAktivno: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    opomba: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sifra: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class PostajnaTocka:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    casPostanka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    geometrija: Optional['Geometrija'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idCona: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idLokacija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajalisce: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPostajnaTocka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPredhodnik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVrstaPrevoza: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    imaCakalnico: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    imaTablo: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    imaVozniRed: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    jeAktivna: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    opomba: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    oznaka: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sifra: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class PostajnaTockaExt:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    geometrija: Optional['Geometrija'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idCona: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idLokacija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajalisce: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajnaTocka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajnaTockaExternal: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVrstaPrevoza: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    imePostajalisca: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ProductCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Relation:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dDistance: Optional['Decimal'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iEndStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iNumberOfStations: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iStID: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStartStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class SetCardRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mCardData: Optional['Card'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPassengerRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mPassengerData: Optional['Passenger'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPosRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mPosData: Optional['Pos'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetTerminalRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mTerminalData: Optional['Terminal'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SifrantNaselij(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iIdGRUS: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iIdNaselje: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iIdObcina: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sImeNaselja: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SifrantObcin(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iIdObcina: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sImeObcine: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SifrantUpravljalcev(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iIdUpravljalca: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sImeUpravljalca: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSifraUpravljalca: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class StatusData(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtDefaultEndTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtDefaultStartTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffStatusId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffStatusType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sTariffStatusName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SubsidyApplication(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    NumberOfLocationsNo1: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    NumberOfLocationsNo2: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    NumberOfLocationsNo3: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    TariffLocationIdNo1: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    TariffLocationIdNo2: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    TariffLocationIdNo3: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtEndTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtStartTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iApplicationStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iApplicationType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iIndexRelation: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iServiceProviderId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iSubsidyStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSubsidyCode: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SubsidyApplicationShort(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSubsidyCode: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SycSubsidiesResponse_1(ResultMessage):
    class Meta:
        name = "SycSubsidiesResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"


@dataclass
class TemporaryCUID(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtEndDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtStartDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class TemporaryCUIDFailed(ExeCardFailedObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class TerminalSubTypeCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalSubTypeId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTerminalTypeId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sTerminalSubTypeName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class TerminalTypeCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalTypeId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sTerminalTypeName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class TransactionExecutionId(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class TransactionExecutionIdFailed(ExeCardFailedObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class UpdateCardRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mCardData: Optional['Card'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class VoznjaOpisEmb(VoznjaOpis):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    casOdhoda: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    casPrihoda: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPostajnaTocka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznjaOpis: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    polnoc: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    postanek: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class VoznjaOpisExt(VoznjaOpis):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    casOdhoda: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    casPrihoda: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dolzina: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    drugiPotniki: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajnaTocka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPredhodnik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVozniRed: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznja: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznjaOpis: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    imePostajneTocke: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    polnoc: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    postanek: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class WhiteList:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCuid: Optional['ArrayOflong'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class WorkStatusCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtEndTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtStartTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ZoneCatalog(CatalogData):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ActivationSAM:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['ActivationSAMRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ActivationSAMResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    ActivationSAMResult: Optional['ActivationSAMResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ActivationSAMRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['ActivationSAMRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ActivationSAMRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    ActivationSAMRestResult: Optional['ActivationSAMResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckActivationCode:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['CheckActivationCodeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckActivationCodeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    CheckActivationCodeResult: Optional['CheckActivationCodeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckActivationCodeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['CheckActivationCodeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckActivationCodeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    CheckActivationCodeRestResult: Optional['CheckActivationCodeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckCardOnSoftBlackList:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['CheckCardOnSoftBlackListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckCardOnSoftBlackListResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    CheckCardOnSoftBlackListResult: Optional['CheckCardOnSoftBlackListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckCardOnSoftBlackListRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['CheckCardOnSoftBlackListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CheckCardOnSoftBlackListRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    CheckCardOnSoftBlackListRestResult: Optional['CheckCardOnSoftBlackListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CreateIdentificationCode:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['CreateIdentificationCodeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CreateIdentificationCodeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    CreateIdentificationCodeResult: Optional['CreateIdentificationCodeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CreateIdentificationCodeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['CreateIdentificationCodeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CreateIdentificationCodeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    CreateIdentificationCodeRestResult: Optional['CreateIdentificationCodeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DelExecutableListResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    DelExecutableListResult: Optional['DelExecutableListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DelExecutableListRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    DelExecutableListRestResult: Optional['DelExecutableListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetAppKeys:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetAppKeysRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetAppKeysResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetAppKeysResult: Optional['GetAppKeysResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetAppKeysRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetAppKeysRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetAppKeysRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetAppKeysRestResult: Optional['GetAppKeysResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetBlackList:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetBlackListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetBlackListRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetBlackListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCUIDsByIdentityNumber:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCUIDsByIdentityNumberRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCUIDsByIdentityNumberRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCUIDsByIdentityNumberRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCard:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCardRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardPassengerStatus:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCardPassengerStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardPassengerStatusRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCardPassengerStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardProducts:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCardProductsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardProductsRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCardProductsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCardRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardStatus:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCardStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardStatusResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCardStatusResult: Optional['GetCardStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardStatusRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCardStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardStatusRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCardStatusRestResult: Optional['GetCardStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetDuplicateData:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetDuplicateDataRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetDuplicateDataRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetDuplicateDataRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetExecutableList:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetExecutableListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetExecutableListRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetExecutableListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPCatalogs:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetIJPPCatalogsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPCatalogsRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetIJPPCatalogsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPDateTime:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetIJPPDateTimeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPDateTimeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetIJPPDateTimeResult: Optional['GetIJPPDateTimeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPDateTimeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetIJPPDateTimeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPDateTimeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetIJPPDateTimeRestResult: Optional['GetIJPPDateTimeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetNearestStations:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetNearestStationaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetNearestStationsRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetNearestStationaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPassenger:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPassengerRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPassengerRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPassengerRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPos:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPosRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPosRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPosRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeZaPrevoznika:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPostajneTockeZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeZaPrevoznikaRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPostajneTockeZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetStations:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetStationsListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetStationsRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetStationsListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetSubTransactions:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetSubTransactionsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetSubTransactionsBySubsidy:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetSubTransactionsBySubsidyRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffTypeTransitionMatrix:
    class Meta:
        name = "GetTariffClassTransitionMatrix"
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetTariffTypeTransitionMatrixRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffTypeTransitionMatrixRest:
    class Meta:
        name = "GetTariffClassTransitionMatrixRest"
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetTariffTypeTransitionMatrixRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTerminal:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetTerminalRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTerminalRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetTerminalRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTransactions:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetTransactionsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTransactionsRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetTransactionsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediIndexZaPrevoznika:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetVozniRediIndexZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediIndexZaPrevoznikaRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetVozniRediIndexZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetWhiteList:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetWhiteListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetWhiteListRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetWhiteListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class IdentifyTransactionParameters:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['IdentifyTransactionParametersRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class IdentifyTransactionParametersRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['IdentifyTransactionParametersRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class RegistrationTerminal:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['RegistrationTerminalRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class RegistrationTerminalRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['RegistrationTerminalRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetBlackList:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetBlackListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetBlackListResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetBlackListResult: Optional['SetBlackListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetBlackListRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetBlackListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetBlackListRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetBlackListRestResult: Optional['SetBlackListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetCardResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetCardResult: Optional['SetCardResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetCardRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetCardRestResult: Optional['SetCardResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetDelovnaNalogaZaPrevoznikaResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetDelovnaNalogaZaPrevoznikaResult: Optional['SetDelovnaNalogaZaPrevoznikResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetDelovnaNalogaZaPrevoznikaRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetDelovnaNalogaZaPrevoznikaRestResult: Optional['SetDelovnaNalogaZaPrevoznikResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetNewCardStatus:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetNewCardStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetNewCardStatusResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetNewCardStatusResult: Optional['SetNewCardStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetNewCardStatusRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetNewCardStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetNewCardStatusRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetNewCardStatusRestResult: Optional['SetNewCardStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPassengerResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetPassengerResult: Optional['SetPassengerResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPassengerRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetPassengerRestResult: Optional['SetPassengerResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPosResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetPosResult: Optional['SetPosResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPosRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetPosRestResult: Optional['SetPosResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetTerminalResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetTerminalResult: Optional['SetTerminalResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetTerminalRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetTerminalRestResult: Optional['SetTerminalResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SpremeniVeljavnostDelovneNalogeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SpremeniVeljavnostDelovneNalogeResult: Optional['SpremeniVeljavnostDelovneNalogeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SpremeniVeljavnostDelovneNalogeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SpremeniVeljavnostDelovneNalogeRestResult: Optional['SpremeniVeljavnostDelovneNalogeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SycSubsidies:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SycSubsidiesRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateActivationCodeDateAndStatus:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['UpdateActivationCodeDateAndStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateActivationCodeDateAndStatusResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    UpdateActivationCodeDateAndStatusResult: Optional['UpdateActivationCodeDateAndStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateActivationCodeDateAndStatusRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['UpdateActivationCodeDateAndStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateActivationCodeDateAndStatusRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    UpdateActivationCodeDateAndStatusRestResult: Optional['UpdateActivationCodeDateAndStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardPassengerStatusResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    UpdateCardPassengerStatusResult: Optional['UpdateCardPassengerStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardPassengerStatusRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    UpdateCardPassengerStatusRestResult: Optional['UpdateCardPassengerStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    UpdateCardResult: Optional['UpdateCardResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    UpdateCardRestResult: Optional['UpdateCardResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfCardPassengerStatus:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    CardPassengerStatus: List['CardPassengerStatus'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfCardRelation:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    CardRelation: List['CardRelation'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfLocationTransitions:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    LocationTransitions: List['LocationTransitions'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfPostajalisce:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Postajalisce: List['Postajalisce'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfPostajnaTocka:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    PostajnaTocka: List['PostajnaTocka'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfPostajnaTockaExt:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    PostajnaTockaExt: List['PostajnaTockaExt'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfSubsidyApplication:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    SubsidyApplication: List['SubsidyApplication'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfVoznjaOpisEmb:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    VoznjaOpisEmb: List['VoznjaOpisEmb'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfVoznjaOpisExt:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    VoznjaOpisExt: List['VoznjaOpisExt'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CardProduct(ExeCardObject):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    bAction: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtActivationEnd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtEndDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtStartDate: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fPriceValue: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iCardRelationIndex: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iInactiveStartPeriod: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iLineId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNoOfTickets: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iNoOfTicketsInterval: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNumberOfPersons: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffClassId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffLocationID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffProductId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffStatusId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lCuid: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mRelationData: Optional['CardRelation'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class CasovniRezim:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    casovniFaktor: Optional['ArrayOfCasovniFaktor'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idCasovniRezim: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    ime: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    jeGlobalni: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class Cona:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    geometrija: Optional['ArrayOfGeometrija'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idCona: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idLokacija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    ime: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    opis: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DelExecutableListRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mDelExecutableData: Optional['ArrayOfDelExecutableList'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DelovnaNaloga:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idDelovniNalog: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idVoznje: Optional['ArrayOfint'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    stevilkaDelovnegaNaloga: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    veljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    veljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    voznjeGrp: Optional['ArrayOfVoznjaGrp'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ExecutableData:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iAction: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mAdditionalCardObject: Optional['ArrayOfExeCardObject'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ExecutableDataFailed:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iAction: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mAdditionalCardFailedObject: Optional['ArrayOfExeCardFailedObject'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetBlackListResponse_1:
    class Meta:
        name = "GetBlackListResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iBlacklistId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iReceiveBlocks: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mBlackListData: Optional['BlackList'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPCatalogsResponse_1:
    class Meta:
        name = "GetIJPPCatalogsResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mCatalogData: Optional['ArrayOfCatalogData'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLokacijeResponse_1:
    class Meta:
        name = "GetLokacijeResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    lokacije: Optional['ArrayOfLokacija'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetNearestStationaResponse:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    stations: Optional['ArrayOfStationDetails'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPassengerResponse_1:
    class Meta:
        name = "GetPassengerResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mPassengerData: Optional['Passenger'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mPassengerListData: Optional['ArrayOfPassenger'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopiResponse_1:
    class Meta:
        name = "GetPrestopiResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    prestopi: Optional['ArrayOfPrestop'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopneTockeResponse_1:
    class Meta:
        name = "GetPrestopneTockeResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    prestopneTocke: Optional['ArrayOfPrestopnaTocka'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrevoznikiResponse_1:
    class Meta:
        name = "GetPrevoznikiResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    prevozniki: Optional['ArrayOfPrevoznik'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelacijeResponse_1:
    class Meta:
        name = "GetRelacijeResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    relacije: Optional['ArrayOfRelacija'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelationResponse_1:
    class Meta:
        name = "GetRelationResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mRelationData: Optional['Relation'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetStationsListResponse:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mStations: Optional['ArrayOfStation'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetSubTransactionsBySubsidyResponse_1:
    class Meta:
        name = "GetSubTransactionsBySubsidyResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mSubTransactionData: Optional['ArrayOfSubTransaction'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetSubTransactionsResponse_1:
    class Meta:
        name = "GetSubTransactionsResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mSubTransactionData: Optional['ArrayOfSubTransaction'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediZaPrevoznikaResponse_1:
    class Meta:
        name = "GetVozniRediZaPrevoznikaResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    vozniRedi: Optional['ArrayOfVozniRed'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetWhiteListResponse_1:
    class Meta:
        name = "GetWhiteListResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    bMoreDataAvailable: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mWhiteListData: Optional['WhiteList'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    uCurrentBlockVersion: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    uCurrentWLVersion: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class IJPPTransaction:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dGPSLattitude: Optional['Decimal'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dGPSLongitude: Optional['Decimal'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtLastSuccessfullTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtStartTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtValidFrom: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dtValidTo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fPriceValue: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fSubFullPrice: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fSubFullPriceReported: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fSubPayment: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iBlacklistId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iBusId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iCurrency: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iErrorCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iExeListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iExecutionStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iExitStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iLineId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNumberOfPersons: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNumberOfProducts: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNumberOfProductsSetInterval: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iOffenseCount: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iOffenseType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iOfflineStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPaymentType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPosId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iSanctionType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iStationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffClassId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffClassTransitionsId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffProductId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTicketStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTicketStatusFormat: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTransactionType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTripId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iWorkOrderId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iZoneLocation: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lCashierId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lLastSuccessfullTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lReceiptNumber: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lRefCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lRefTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    lTransactionExecutionId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mCardRelationData: Optional['CardRelation'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sCashierName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sNotes: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sPurchaseOrder: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sSubsidyId: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class IdentifyData:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    bTerminalEnabled: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtCurrentTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iBlacklistId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iBusOperatorId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iExeListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iExeListInterval: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iLineListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iLineSectionCRC: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iRegimeCRC: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iSamplingPeriod: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iServiceCallInterval: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iStationCRC: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iStationPointCRC: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iSyncPeriod: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mTariffdef: Optional['ArrayOfTariffDef'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mTransitionMatrix: Optional['ArrayOfTransitionMatrix'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class LinijskiOdsek:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    casVoznje: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dolzina: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dolzina2D: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dolzina3D: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    dolzinaAVRIS: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    geometrija: Optional['ArrayOfGeometrija'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idLinijskiOdsek: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPostajnaTockaDo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPostajnaTockaOd: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    idPredhodnik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idRelacija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idStatus: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    opomba: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ProcessTransactionsResponse_1:
    class Meta:
        name = "ProcessTransactionsResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mTransactionExecutonStatus: Optional['ArrayOfTransactionExecutionStatus'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class RegistrationTerminalResponse_1:
    class Meta:
        name = "RegistrationTerminalResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mSSLCertificate: Optional['ArrayOfSSLCertificate'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Rezim:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idPredhodnik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idRezim: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    interval: Optional['ArrayOfRezimInterval'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    opis: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    oznaka: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    privzetiDelovniVektor: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    termini: Optional['ArrayOfRezimTermin'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class TariffProduct:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    bAbsolutePurchaseTimeValidity: Optional['ArrayOfbase64Binary'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    bAbsoluteValidationTimeValidity: Optional['ArrayOfbase64Binary'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    bIsConditional: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    bIsSwitching: Optional['bool'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    fVAT: Optional['float'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iActiveStartPeriod: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iActiveTimeOffsetEndTime: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iActiveTimeOffsetStartTime: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iActiveTimeOffsetTimeUnit: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iActiveTimeQuantity: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iActiveTimeUnit: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iActiveValidationPriority: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iDirection: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iDisablePurchaseTerminalType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iInactiveOffsetEndTime: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iInactiveOffsetStartTime: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iInactiveOffsetTimeUnit: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iInactiveStartPeriod: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iInactiveTimeQuantity: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iInactiveTimeUnit: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iInactiveValidationPriority: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNumberOfProducts: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNumberOfProductsSetExtensionQuantity: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNumberOfProductsSetExtensionUnit: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iNumberOfProductsSetPeriod: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iProdcutCardLimit: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iProductTimePriority: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iProductType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPurchaseEndOffset: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPurchaseEndOffsetTimeUnit: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPurchaseStartOffset: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iPurchaseStartOffsetTimeUnit: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffProductId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mConditionalProductData: Optional['ArrayOfConditionalProduct'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sTariffProductName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class VozniRedIndex:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idVozniRed: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    veljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    veljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    voznje: Optional['ArrayOfVoznjaIndex'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCUIDsByIdentityNumberResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCUIDsByIdentityNumberResult: Optional['GetCUIDsByIdentityNumberResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCUIDsByIdentityNumberRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCUIDsByIdentityNumberRestResult: Optional['GetCUIDsByIdentityNumberResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCardResult: Optional['GetCardResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCardRestResult: Optional['GetCardResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCasovniRezimi:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCasovniRezimiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCasovniRezimiRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetCasovniRezimiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCone:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetConaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetConeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetConaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLinijskiOdseki:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetLinijskiOdsekiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLinijskiOdsekiRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetLinijskiOdsekiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLokacije:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetLokacijeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLokacijeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetLokacijeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPosResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPosResult: Optional['GetPosResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPosRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPosRestResult: Optional['GetPosResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajalisca:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPostajaliscaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajaliscaRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPostajaliscaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTocke:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPostajneTockeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPostajneTockeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopi:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPrestopiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopiRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPrestopiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopneTocke:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPrestopneTockeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopneTockeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPrestopneTockeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrevozniki:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPrevoznikiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrevoznikiRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetPrevoznikiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetProductPrice:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetProductPriceRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetProductPriceResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetProductPriceResult: Optional['GetProductPriceResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetProductPriceRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetProductPriceRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetProductPriceRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetProductPriceRestResult: Optional['GetProductPriceResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelacije:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetRelacijeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelacijeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetRelacijeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelation:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetRelationRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelationRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetRelationRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimi:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetRezimiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetRezimiRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiZaPrevoznika:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetRezimiZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiZaPrevoznikaRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetRezimiZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariff:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetTariffRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetTariffRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTerminalResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetTerminalResult: Optional['GetTerminalResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTerminalRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetTerminalRestResult: Optional['GetTerminalResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediZaPrevoznika:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetVozniRediZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediZaPrevoznikaRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['GetVozniRediZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class IIJPPServiceSoap_ActivationSAM_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_ActivationSAM_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        ActivationSAM: Optional['ActivationSAM'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_ActivationSAM_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_ActivationSAM_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        ActivationSAMResponse: Optional['ActivationSAMResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_ActivationSAM_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_CheckActivationCode_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_CheckActivationCode_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        CheckActivationCode: Optional['CheckActivationCode'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_CheckActivationCode_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_CheckActivationCode_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        CheckActivationCodeResponse: Optional['CheckActivationCodeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_CheckActivationCode_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_CheckCardOnSoftBlackList_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_CheckCardOnSoftBlackList_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        CheckCardOnSoftBlackList: Optional['CheckCardOnSoftBlackList'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_CheckCardOnSoftBlackList_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_CheckCardOnSoftBlackList_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        CheckCardOnSoftBlackListResponse: Optional['CheckCardOnSoftBlackListResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_CheckCardOnSoftBlackList_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_CreateIdentificationCode_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_CreateIdentificationCode_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        CreateIdentificationCode: Optional['CreateIdentificationCode'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_CreateIdentificationCode_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_CreateIdentificationCode_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        CreateIdentificationCodeResponse: Optional['CreateIdentificationCodeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_CreateIdentificationCode_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_DelExecutableList_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_DelExecutableList_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        DelExecutableListResponse: Optional['DelExecutableListResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_DelExecutableList_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetAppKeys_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetAppKeys_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetAppKeys: Optional['GetAppKeys'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetAppKeys_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetAppKeys_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetAppKeysResponse: Optional['GetAppKeysResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetAppKeys_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetBlackList_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetBlackList_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetBlackList: Optional['GetBlackList'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetCUIDsByIdentityNumber_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCUIDsByIdentityNumber_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCUIDsByIdentityNumber: Optional['GetCUIDsByIdentityNumber'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetCardPassengerStatus_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCardPassengerStatus_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCardPassengerStatus: Optional['GetCardPassengerStatus'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetCardProducts_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCardProducts_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCardProducts: Optional['GetCardProducts'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetCardStatus_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCardStatus_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCardStatus: Optional['GetCardStatus'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetCardStatus_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCardStatus_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCardStatusResponse: Optional['GetCardStatusResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetCardStatus_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetCard_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCard_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCard: Optional['GetCard'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetDuplicateData_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetDuplicateData_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetDuplicateData: Optional['GetDuplicateData'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetExecutableList_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetExecutableList_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetExecutableList: Optional['GetExecutableList'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetIJPPCatalogs_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetIJPPCatalogs_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetIJPPCatalogs: Optional['GetIJPPCatalogs'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetIJPPDateTime_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetIJPPDateTime_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetIJPPDateTime: Optional['GetIJPPDateTime'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetIJPPDateTime_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetIJPPDateTime_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetIJPPDateTimeResponse: Optional['GetIJPPDateTimeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetIJPPDateTime_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetNearestStations_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetNearestStations_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetNearestStations: Optional['GetNearestStations'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetPassenger_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPassenger_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPassenger: Optional['GetPassenger'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetPos_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPos_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPos: Optional['GetPos'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetPostajneTockeZaPrevoznika_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPostajneTockeZaPrevoznika_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPostajneTockeZaPrevoznika: Optional['GetPostajneTockeZaPrevoznika'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetStations_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetStations_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetStations: Optional['GetStations'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetSubTransactionsBySubsidy_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetSubTransactionsBySubsidy_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetSubTransactionsBySubsidy: Optional['GetSubTransactionsBySubsidy'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetSubTransactions_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetSubTransactions_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetSubTransactions: Optional['GetSubTransactions'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetTariffTypeTransitionMatrix_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetTariffTypeTransitionMatrix_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetTariffClassTransitionMatrix: Optional['GetTariffTypeTransitionMatrix'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetTerminal_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetTerminal_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetTerminal: Optional['GetTerminal'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetTransactions_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetTransactions_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetTransactions: Optional['GetTransactions'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetVozniRediIndexZaPrevoznika_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetVozniRediIndexZaPrevoznika_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetVozniRediIndexZaPrevoznika: Optional['GetVozniRediIndexZaPrevoznika'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetWhiteList_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetWhiteList_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetWhiteList: Optional['GetWhiteList'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_IdentifyTransactionParameters_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_IdentifyTransactionParameters_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        IdentifyTransactionParameters: Optional['IdentifyTransactionParameters'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_RegistrationTerminal_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_RegistrationTerminal_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        RegistrationTerminal: Optional['RegistrationTerminal'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_SetBlackList_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetBlackList_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetBlackList: Optional['SetBlackList'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_SetBlackList_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetBlackList_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetBlackListResponse: Optional['SetBlackListResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SetBlackList_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_SetCard_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetCard_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetCardResponse: Optional['SetCardResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SetCard_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_SetDelovnaNalogaZaPrevoznika_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetDelovnaNalogaZaPrevoznika_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetDelovnaNalogaZaPrevoznikaResponse: Optional['SetDelovnaNalogaZaPrevoznikaResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SetDelovnaNalogaZaPrevoznika_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_SetNewCardStatus_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetNewCardStatus_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetNewCardStatus: Optional['SetNewCardStatus'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_SetNewCardStatus_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetNewCardStatus_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetNewCardStatusResponse: Optional['SetNewCardStatusResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SetNewCardStatus_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_SetPassenger_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetPassenger_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetPassengerResponse: Optional['SetPassengerResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SetPassenger_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_SetPos_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetPos_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetPosResponse: Optional['SetPosResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SetPos_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_SetTerminal_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetTerminal_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetTerminalResponse: Optional['SetTerminalResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SetTerminal_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_SpremeniVeljavnostDelovneNaloge_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SpremeniVeljavnostDelovneNaloge_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SpremeniVeljavnostDelovneNalogeResponse: Optional['SpremeniVeljavnostDelovneNalogeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SpremeniVeljavnostDelovneNaloge_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_SycSubsidies_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SycSubsidies_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SycSubsidies: Optional['SycSubsidies'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_UpdateActivationCodeDateAndStatus_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_UpdateActivationCodeDateAndStatus_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        UpdateActivationCodeDateAndStatus: Optional['UpdateActivationCodeDateAndStatus'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_UpdateActivationCodeDateAndStatus_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_UpdateActivationCodeDateAndStatus_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        UpdateActivationCodeDateAndStatusResponse: Optional['UpdateActivationCodeDateAndStatusResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_UpdateActivationCodeDateAndStatus_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_UpdateCardPassengerStatus_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_UpdateCardPassengerStatus_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        UpdateCardPassengerStatusResponse: Optional['UpdateCardPassengerStatusResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_UpdateCardPassengerStatus_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_UpdateCard_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_UpdateCard_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        UpdateCardResponse: Optional['UpdateCardResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_UpdateCard_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class SetCard:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetCardRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetCardRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetCardRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPassenger:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetPassengerRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPassengerRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetPassengerRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPos:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetPosRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetPosRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetPosRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetTerminal:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetTerminalRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetTerminalRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetTerminalRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SycSubsidiesResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SycSubsidiesResult: Optional['SycSubsidiesResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCard:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['UpdateCardRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['UpdateCardRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfCardProduct:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    CardProduct: List['CardProduct'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfCasovniRezim:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    CasovniRezim: List['CasovniRezim'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfCona:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Cona: List['Cona'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfExecutableData:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    ExecutableData: List['ExecutableData'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfExecutableDataFailed:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    ExecutableDataFailed: List['ExecutableDataFailed'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfIJPPTransaction:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    IJPPTransaction: List['IJPPTransaction'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfLinijskiOdsek:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    LinijskiOdsek: List['LinijskiOdsek'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfRezim:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    Rezim: List['Rezim'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfTariffProduct:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    TariffProduct: List['TariffProduct'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfVozniRedIndex:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    VozniRedIndex: List['VozniRedIndex'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardPassengerStatusResponse_1:
    class Meta:
        name = "GetCardPassengerStatusResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mCardPassengerStatusData: Optional['CardPassengerStatus'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mSubsidyApplication: Optional['ArrayOfSubsidyApplication'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mWorkStatus: Optional['ArrayOfWorkStatus'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajaliscaResponse_1:
    class Meta:
        name = "GetPostajaliscaResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    postajalisca: Optional['ArrayOfPostajalisce'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeResponse_1:
    class Meta:
        name = "GetPostajneTockeResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    postajneTocke: Optional['ArrayOfPostajnaTocka'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeZaPrevoznikaResponse_1:
    class Meta:
        name = "GetPostajneTockeZaPrevoznikaResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    postajneTocke: Optional['ArrayOfPostajnaTockaExt'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class IdentifyTransactionParametersResponse_1:
    class Meta:
        name = "IdentifyTransactionParametersResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mIdentifyData: Optional['IdentifyData'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetDelovnaNalogaZaPrevoznikaRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    delovnaNaloga: Optional['DelovnaNaloga'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPrevoznika: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class SpremeniVeljavnostDelovneNalogeRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    delovnaNaloga: Optional['DelovnaNaloga'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPrevoznika: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    newVeljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    newVeljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )


@dataclass
class TariffTypeTransitions:
    class Meta:
        name = "TariffClassTransitions"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mLocationData: Optional['ArrayOfLocation'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mLocationTransitionsData: Optional['ArrayOfLocationTransitions'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardPassengerStatusRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    lCUID: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mCardStatusData: Optional['ArrayOfCardPassengerStatus'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mSubsidyApplication: Optional['ArrayOfSubsidyApplication'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mWorkStatus: Optional['ArrayOfWorkStatus'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class VoznjaEmb(Voznja):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idKooperant: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idRezim: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznja: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    oznaka: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    voznjeOpisi: Optional['ArrayOfVoznjaOpisEmb'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class VoznjaExt(Voznja):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idKooperant: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPredhodnik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idRezim: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVozniRed: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznja: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVoznjaExternal: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    oznaka: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    oznakaPoti: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    stevilka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    voznjeOpisi: Optional['ArrayOfVoznjaOpisExt'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DelExecutableList:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['DelExecutableListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DelExecutableListRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['DelExecutableListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetBlackListResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetBlackListResult: Optional['GetBlackListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetBlackListRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetBlackListRestResult: Optional['GetBlackListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPCatalogsResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetIJPPCatalogsResult: Optional['GetIJPPCatalogsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetIJPPCatalogsRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetIJPPCatalogsRestResult: Optional['GetIJPPCatalogsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLokacijeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetLokacijeResult: Optional['GetLokacijeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLokacijeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetLokacijeRestResult: Optional['GetLokacijeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetNearestStationsResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetNearestStationsResult: Optional['GetNearestStationaResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetNearestStationsRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetNearestStationsRestResult: Optional['GetNearestStationaResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPassengerResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPassengerResult: Optional['GetPassengerResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPassengerRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPassengerRestResult: Optional['GetPassengerResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopiResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPrestopiResult: Optional['GetPrestopiResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopiRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPrestopiRestResult: Optional['GetPrestopiResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopneTockeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPrestopneTockeResult: Optional['GetPrestopneTockeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrestopneTockeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPrestopneTockeRestResult: Optional['GetPrestopneTockeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrevoznikiResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPrevoznikiResult: Optional['GetPrevoznikiResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPrevoznikiRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPrevoznikiRestResult: Optional['GetPrevoznikiResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelacijeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetRelacijeResult: Optional['GetRelacijeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelacijeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetRelacijeRestResult: Optional['GetRelacijeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelationResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetRelationResult: Optional['GetRelationResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRelationRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetRelationRestResult: Optional['GetRelationResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetStationsResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetStationsResult: Optional['GetStationsListResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetStationsRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetStationsRestResult: Optional['GetStationsListResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetSubTransactionsBySubsidyResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetSubTransactionsBySubsidyResult: Optional['GetSubTransactionsBySubsidyResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetSubTransactionsResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetSubTransactionsResult: Optional['GetSubTransactionsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediZaPrevoznikaResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetVozniRediZaPrevoznikaResult: Optional['GetVozniRediZaPrevoznikaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediZaPrevoznikaRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetVozniRediZaPrevoznikaRestResult: Optional['GetVozniRediZaPrevoznikaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetWhiteListResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetWhiteListResult: Optional['GetWhiteListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetWhiteListRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetWhiteListRestResult: Optional['GetWhiteListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


class IIJPPServiceSoap_ActivationSAM:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/ActivationSAM"
    input = IIJPPServiceSoap_ActivationSAM_input
    output = IIJPPServiceSoap_ActivationSAM_output


class IIJPPServiceSoap_CheckActivationCode:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/CheckActivationCode"
    input = IIJPPServiceSoap_CheckActivationCode_input
    output = IIJPPServiceSoap_CheckActivationCode_output


class IIJPPServiceSoap_CheckCardOnSoftBlackList:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/CheckCardOnSoftBlackList"
    input = IIJPPServiceSoap_CheckCardOnSoftBlackList_input
    output = IIJPPServiceSoap_CheckCardOnSoftBlackList_output


class IIJPPServiceSoap_CreateIdentificationCode:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/CreateIdentificationCode"
    input = IIJPPServiceSoap_CreateIdentificationCode_input
    output = IIJPPServiceSoap_CreateIdentificationCode_output


class IIJPPServiceSoap_GetAppKeys:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetAppKeys"
    input = IIJPPServiceSoap_GetAppKeys_input
    output = IIJPPServiceSoap_GetAppKeys_output


@dataclass
class IIJPPServiceSoap_GetCUIDsByIdentityNumber_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCUIDsByIdentityNumber_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCUIDsByIdentityNumberResponse: Optional['GetCUIDsByIdentityNumberResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetCUIDsByIdentityNumber_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetCardStatus:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetCardStatus"
    input = IIJPPServiceSoap_GetCardStatus_input
    output = IIJPPServiceSoap_GetCardStatus_output


@dataclass
class IIJPPServiceSoap_GetCard_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCard_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCardResponse: Optional['GetCardResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetCard_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetCasovniRezimi_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCasovniRezimi_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCasovniRezimi: Optional['GetCasovniRezimi'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetCone_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCone_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCone: Optional['GetCone'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


class IIJPPServiceSoap_GetIJPPDateTime:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetIJPPDateTime"
    input = IIJPPServiceSoap_GetIJPPDateTime_input
    output = IIJPPServiceSoap_GetIJPPDateTime_output


@dataclass
class IIJPPServiceSoap_GetLinijskiOdseki_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetLinijskiOdseki_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetLinijskiOdseki: Optional['GetLinijskiOdseki'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetLokacije_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetLokacije_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetLokacije: Optional['GetLokacije'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetPos_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPos_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPosResponse: Optional['GetPosResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetPos_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetPostajalisca_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPostajalisca_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPostajalisca: Optional['GetPostajalisca'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetPostajneTocke_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPostajneTocke_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPostajneTocke: Optional['GetPostajneTocke'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetPrestopi_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPrestopi_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPrestopi: Optional['GetPrestopi'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetPrestopneTocke_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPrestopneTocke_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPrestopneTocke: Optional['GetPrestopneTocke'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetPrevozniki_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPrevozniki_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPrevozniki: Optional['GetPrevozniki'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetProductPrice_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetProductPrice_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetProductPrice: Optional['GetProductPrice'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetProductPrice_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetProductPrice_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetProductPriceResponse: Optional['GetProductPriceResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetProductPrice_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetRelacije_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetRelacije_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetRelacije: Optional['GetRelacije'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetRelation_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetRelation_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetRelation: Optional['GetRelation'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetRezimiZaPrevoznika_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetRezimiZaPrevoznika_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetRezimiZaPrevoznika: Optional['GetRezimiZaPrevoznika'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetRezimi_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetRezimi_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetRezimi: Optional['GetRezimi'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetTariff_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetTariff_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetTariff: Optional['GetTariff'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetTerminal_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetTerminal_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetTerminalResponse: Optional['GetTerminalResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetTerminal_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetVozniRediZaPrevoznika_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetVozniRediZaPrevoznika_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetVozniRediZaPrevoznika: Optional['GetVozniRediZaPrevoznika'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


class IIJPPServiceSoap_SetBlackList:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SetBlackList"
    input = IIJPPServiceSoap_SetBlackList_input
    output = IIJPPServiceSoap_SetBlackList_output


@dataclass
class IIJPPServiceSoap_SetCard_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetCard_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetCard: Optional['SetCard'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


class IIJPPServiceSoap_SetNewCardStatus:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SetNewCardStatus"
    input = IIJPPServiceSoap_SetNewCardStatus_input
    output = IIJPPServiceSoap_SetNewCardStatus_output


@dataclass
class IIJPPServiceSoap_SetPassenger_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetPassenger_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetPassenger: Optional['SetPassenger'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_SetPos_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetPos_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetPos: Optional['SetPos'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_SetTerminal_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetTerminal_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetTerminal: Optional['SetTerminal'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_SycSubsidies_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SycSubsidies_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SycSubsidiesResponse: Optional['SycSubsidiesResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SycSubsidies_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_UpdateActivationCodeDateAndStatus:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/UpdateActivationCodeDateAndStatus"
    input = IIJPPServiceSoap_UpdateActivationCodeDateAndStatus_input
    output = IIJPPServiceSoap_UpdateActivationCodeDateAndStatus_output


@dataclass
class IIJPPServiceSoap_UpdateCard_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_UpdateCard_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        UpdateCard: Optional['UpdateCard'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class ProcessTransactionsResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    ProcessTransactionsResult: Optional['ProcessTransactionsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ProcessTransactionsRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    ProcessTransactionsRestResult: Optional['ProcessTransactionsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class RegistrationTerminalResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    RegistrationTerminalResult: Optional['RegistrationTerminalResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class RegistrationTerminalRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    RegistrationTerminalRestResult: Optional['RegistrationTerminalResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfVoznjaEmb:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    VoznjaEmb: List['VoznjaEmb'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfVoznjaExt:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    VoznjaExt: List['VoznjaExt'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class DuplicateData:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mCard: Optional['Card'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mCardPassengerStatuses: Optional['ArrayOfCardPassengerStatus'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mCardProducts: Optional['ArrayOfCardProduct'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mCardRelations: Optional['ArrayOfCardRelation'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mPassenger: Optional['Passenger'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mSubsidyApplication: Optional['ArrayOfSubsidyApplication'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mWorkStatus: Optional['ArrayOfWorkStatus'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardProductsResponse_1:
    class Meta:
        name = "GetCardProductsResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mCardProductData: Optional['ArrayOfCardProduct'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCasovniRezimiResponse_1:
    class Meta:
        name = "GetCasovniRezimiResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    casovniRezimi: Optional['ArrayOfCasovniRezim'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetConaResponse:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    cona: Optional['ArrayOfCona'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetExecutableListResponse_1:
    class Meta:
        name = "GetExecutableListResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iBlocksInLastEL: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iCurrentExeListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iExeListCRC: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iReceiveBlocks: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iResetExeListId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mExecutableData: Optional['ArrayOfExecutableData'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLinijskiOdeskiResponse:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    linijskiOdseki: Optional['ArrayOfLinijskiOdsek'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiResponse_1:
    class Meta:
        name = "GetRezimiResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    rezimi: Optional['ArrayOfRezim'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiZaPrevoznikaResponse_1:
    class Meta:
        name = "GetRezimiZaPrevoznikaResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    rezimi: Optional['ArrayOfRezim'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffTypeTransitionMatrixResponse_1:
    class Meta:
        name = "GetTariffClassTransitionMatrixResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mTariffClassTransitionData: Optional['TariffTypeTransitions'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTransactionsResponse_1:
    class Meta:
        name = "GetTransactionsResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mIJPPTransactionData: Optional['ArrayOfIJPPTransaction'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediIndexZaPrevoznikaResponse_1:
    class Meta:
        name = "GetVozniRediIndexZaPrevoznikaResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mVozniRedi: Optional['ArrayOfVozniRedIndex'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ProcessTransactionsRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iTerminalId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mIJPPTransactionData: Optional['ArrayOfIJPPTransaction'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ServiceProviderTariff:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    dtEndTariffTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    dtStartTariffTime: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iCurrencyCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    iTariffId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffLocationId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffType: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mTariffClassData: Optional['ArrayOfTariffType'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mTariffPriceData: Optional['ArrayOfTariffPrice'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mTariffProductData: Optional['ArrayOfTariffProduct'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mTariffStatusData: Optional['ArrayOfTariffStatus'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sTariffLocationName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetExecutableListRequest:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    mExecutableData: Optional['ArrayOfExecutableData'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetExecutableListResponse_1:
    class Meta:
        name = "SetExecutableListResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mCardFailedObject: Optional['ArrayOfExecutableDataFailed'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardPassengerStatusResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCardPassengerStatusResult: Optional['GetCardPassengerStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardPassengerStatusRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCardPassengerStatusRestResult: Optional['GetCardPassengerStatusResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajaliscaResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPostajaliscaResult: Optional['GetPostajaliscaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajaliscaRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPostajaliscaRestResult: Optional['GetPostajaliscaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPostajneTockeResult: Optional['GetPostajneTockeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPostajneTockeRestResult: Optional['GetPostajneTockeResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeZaPrevoznikaResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPostajneTockeZaPrevoznikaResult: Optional['GetPostajneTockeZaPrevoznikaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetPostajneTockeZaPrevoznikaRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetPostajneTockeZaPrevoznikaRestResult: Optional['GetPostajneTockeZaPrevoznikaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class IIJPPServiceSoap_DelExecutableList_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_DelExecutableList_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        DelExecutableList: Optional['DelExecutableList'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_GetBlackList_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetBlackList_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetBlackListResponse: Optional['GetBlackListResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetBlackList_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetCUIDsByIdentityNumber:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetCUIDsByIdentityNumber"
    input = IIJPPServiceSoap_GetCUIDsByIdentityNumber_input
    output = IIJPPServiceSoap_GetCUIDsByIdentityNumber_output


class IIJPPServiceSoap_GetCard:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetCard"
    input = IIJPPServiceSoap_GetCard_input
    output = IIJPPServiceSoap_GetCard_output


@dataclass
class IIJPPServiceSoap_GetIJPPCatalogs_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetIJPPCatalogs_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetIJPPCatalogsResponse: Optional['GetIJPPCatalogsResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetIJPPCatalogs_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetLokacije_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetLokacije_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetLokacijeResponse: Optional['GetLokacijeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetLokacije_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetNearestStations_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetNearestStations_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetNearestStationsResponse: Optional['GetNearestStationsResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetNearestStations_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetPassenger_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPassenger_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPassengerResponse: Optional['GetPassengerResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetPassenger_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetPos:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetPos"
    input = IIJPPServiceSoap_GetPos_input
    output = IIJPPServiceSoap_GetPos_output


@dataclass
class IIJPPServiceSoap_GetPrestopi_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPrestopi_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPrestopiResponse: Optional['GetPrestopiResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetPrestopi_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetPrestopneTocke_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPrestopneTocke_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPrestopneTockeResponse: Optional['GetPrestopneTockeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetPrestopneTocke_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetPrevozniki_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPrevozniki_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPrevoznikiResponse: Optional['GetPrevoznikiResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetPrevozniki_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetProductPrice:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetProductPrice"
    input = IIJPPServiceSoap_GetProductPrice_input
    output = IIJPPServiceSoap_GetProductPrice_output


@dataclass
class IIJPPServiceSoap_GetRelacije_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetRelacije_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetRelacijeResponse: Optional['GetRelacijeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetRelacije_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetRelation_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetRelation_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetRelationResponse: Optional['GetRelationResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetRelation_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetStations_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetStations_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetStationsResponse: Optional['GetStationsResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetStations_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetSubTransactionsBySubsidy_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetSubTransactionsBySubsidy_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetSubTransactionsBySubsidyResponse: Optional['GetSubTransactionsBySubsidyResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetSubTransactionsBySubsidy_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetSubTransactions_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetSubTransactions_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetSubTransactionsResponse: Optional['GetSubTransactionsResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetSubTransactions_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetTerminal:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetTerminal"
    input = IIJPPServiceSoap_GetTerminal_input
    output = IIJPPServiceSoap_GetTerminal_output


@dataclass
class IIJPPServiceSoap_GetVozniRediZaPrevoznika_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetVozniRediZaPrevoznika_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetVozniRediZaPrevoznikaResponse: Optional['GetVozniRediZaPrevoznikaResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetVozniRediZaPrevoznika_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetWhiteList_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetWhiteList_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetWhiteListResponse: Optional['GetWhiteListResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetWhiteList_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_ProcessTransactions_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_ProcessTransactions_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        ProcessTransactionsResponse: Optional['ProcessTransactionsResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_ProcessTransactions_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_RegistrationTerminal_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_RegistrationTerminal_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        RegistrationTerminalResponse: Optional['RegistrationTerminalResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_RegistrationTerminal_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_SetCard:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SetCard"
    input = IIJPPServiceSoap_SetCard_input
    output = IIJPPServiceSoap_SetCard_output


class IIJPPServiceSoap_SetPassenger:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SetPassenger"
    input = IIJPPServiceSoap_SetPassenger_input
    output = IIJPPServiceSoap_SetPassenger_output


class IIJPPServiceSoap_SetPos:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SetPos"
    input = IIJPPServiceSoap_SetPos_input
    output = IIJPPServiceSoap_SetPos_output


class IIJPPServiceSoap_SetTerminal:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SetTerminal"
    input = IIJPPServiceSoap_SetTerminal_input
    output = IIJPPServiceSoap_SetTerminal_output


class IIJPPServiceSoap_SycSubsidies:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SycSubsidies"
    input = IIJPPServiceSoap_SycSubsidies_input
    output = IIJPPServiceSoap_SycSubsidies_output


class IIJPPServiceSoap_UpdateCard:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/UpdateCard"
    input = IIJPPServiceSoap_UpdateCard_input
    output = IIJPPServiceSoap_UpdateCard_output


@dataclass
class IdentifyTransactionParametersResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    IdentifyTransactionParametersResult: Optional['IdentifyTransactionParametersResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class IdentifyTransactionParametersRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    IdentifyTransactionParametersRestResult: Optional['IdentifyTransactionParametersResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetDelovnaNalogaZaPrevoznika:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetDelovnaNalogaZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetDelovnaNalogaZaPrevoznikaRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetDelovnaNalogaZaPrevoznikaRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SpremeniVeljavnostDelovneNaloge:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SpremeniVeljavnostDelovneNalogeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SpremeniVeljavnostDelovneNalogeRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SpremeniVeljavnostDelovneNalogeRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardPassengerStatus:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['UpdateCardPassengerStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class UpdateCardPassengerStatusRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['UpdateCardPassengerStatusRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ArrayOfServiceProviderTariff:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    ServiceProviderTariff: List['ServiceProviderTariff'] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetDuplicateDataResponse_1:
    class Meta:
        name = "GetDuplicateDataResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mDuplicateData: Optional['DuplicateData'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class VozniRedEmb(VozniRed):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    idVozniRed: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVrstaPrevoza: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    voznje: Optional['ArrayOfVoznjaEmb'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class VozniRedExt(VozniRed):
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    drugiPotniki: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajalisceDo: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPostajalisceOd: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPredhodnik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idPrevoznik: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idTipPrevoza: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVozniRed: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVozniRedExternal: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    idVrstaPrevoza: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    imePostajaliscaOd: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    imePostajalisceDo: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    opomba: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    postajalisceVia: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    stevilka: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostDo: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    veljavnostOd: Optional['XmlDateTime'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    verzija: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    voznje: Optional['ArrayOfVoznjaExt'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardProductsResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCardProductsResult: Optional['GetCardProductsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCardProductsRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCardProductsRestResult: Optional['GetCardProductsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCasovniRezimiResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCasovniRezimiResult: Optional['GetCasovniRezimiResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetCasovniRezimiRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetCasovniRezimiRestResult: Optional['GetCasovniRezimiResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetConeResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetConeResult: Optional['GetConaResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetConeRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetConeRestResult: Optional['GetConaResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetExecutableListResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetExecutableListResult: Optional['GetExecutableListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetExecutableListRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetExecutableListRestResult: Optional['GetExecutableListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLinijskiOdsekiResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetLinijskiOdsekiResult: Optional['GetLinijskiOdeskiResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetLinijskiOdsekiRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetLinijskiOdsekiRestResult: Optional['GetLinijskiOdeskiResponse'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetRezimiResult: Optional['GetRezimiResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetRezimiRestResult: Optional['GetRezimiResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiZaPrevoznikaResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetRezimiZaPrevoznikaResult: Optional['GetRezimiZaPrevoznikaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetRezimiZaPrevoznikaRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetRezimiZaPrevoznikaRestResult: Optional['GetRezimiZaPrevoznikaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffTypeTransitionMatrixResponse:
    class Meta:
        name = "GetTariffClassTransitionMatrixResponse"
        namespace = "http://tempuri.org/"

    GetTariffClassTransitionMatrixResult: Optional['GetTariffTypeTransitionMatrixResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffTypeTransitionMatrixRestResponse:
    class Meta:
        name = "GetTariffClassTransitionMatrixRestResponse"
        namespace = "http://tempuri.org/"

    GetTariffClassTransitionMatrixRestResult: Optional['GetTariffTypeTransitionMatrixResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTransactionsResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetTransactionsResult: Optional['GetTransactionsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTransactionsRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetTransactionsRestResult: Optional['GetTransactionsResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediIndexZaPrevoznikaResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetVozniRediIndexZaPrevoznikaResult: Optional['GetVozniRediIndexZaPrevoznikaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetVozniRediIndexZaPrevoznikaRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetVozniRediIndexZaPrevoznikaRestResult: Optional['GetVozniRediIndexZaPrevoznikaResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


class IIJPPServiceSoap_DelExecutableList:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/DelExecutableList"
    input = IIJPPServiceSoap_DelExecutableList_input
    output = IIJPPServiceSoap_DelExecutableList_output


class IIJPPServiceSoap_GetBlackList:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetBlackList"
    input = IIJPPServiceSoap_GetBlackList_input
    output = IIJPPServiceSoap_GetBlackList_output


@dataclass
class IIJPPServiceSoap_GetCardPassengerStatus_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCardPassengerStatus_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCardPassengerStatusResponse: Optional['GetCardPassengerStatusResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetCardPassengerStatus_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetIJPPCatalogs:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetIJPPCatalogs"
    input = IIJPPServiceSoap_GetIJPPCatalogs_input
    output = IIJPPServiceSoap_GetIJPPCatalogs_output


class IIJPPServiceSoap_GetLokacije:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetLokacije"
    input = IIJPPServiceSoap_GetLokacije_input
    output = IIJPPServiceSoap_GetLokacije_output


class IIJPPServiceSoap_GetNearestStations:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetNearestStations"
    input = IIJPPServiceSoap_GetNearestStations_input
    output = IIJPPServiceSoap_GetNearestStations_output


class IIJPPServiceSoap_GetPassenger:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetPassenger"
    input = IIJPPServiceSoap_GetPassenger_input
    output = IIJPPServiceSoap_GetPassenger_output


@dataclass
class IIJPPServiceSoap_GetPostajalisca_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPostajalisca_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPostajaliscaResponse: Optional['GetPostajaliscaResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetPostajalisca_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetPostajneTockeZaPrevoznika_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPostajneTockeZaPrevoznika_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPostajneTockeZaPrevoznikaResponse: Optional['GetPostajneTockeZaPrevoznikaResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetPostajneTockeZaPrevoznika_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetPostajneTocke_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetPostajneTocke_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetPostajneTockeResponse: Optional['GetPostajneTockeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetPostajneTocke_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetPrestopi:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetPrestopi"
    input = IIJPPServiceSoap_GetPrestopi_input
    output = IIJPPServiceSoap_GetPrestopi_output


class IIJPPServiceSoap_GetPrestopneTocke:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetPrestopneTocke"
    input = IIJPPServiceSoap_GetPrestopneTocke_input
    output = IIJPPServiceSoap_GetPrestopneTocke_output


class IIJPPServiceSoap_GetPrevozniki:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetPrevozniki"
    input = IIJPPServiceSoap_GetPrevozniki_input
    output = IIJPPServiceSoap_GetPrevozniki_output


class IIJPPServiceSoap_GetRelacije:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetRelacije"
    input = IIJPPServiceSoap_GetRelacije_input
    output = IIJPPServiceSoap_GetRelacije_output


class IIJPPServiceSoap_GetRelation:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetRelation"
    input = IIJPPServiceSoap_GetRelation_input
    output = IIJPPServiceSoap_GetRelation_output


class IIJPPServiceSoap_GetStations:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetStations"
    input = IIJPPServiceSoap_GetStations_input
    output = IIJPPServiceSoap_GetStations_output


class IIJPPServiceSoap_GetSubTransactions:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetSubTransactions"
    input = IIJPPServiceSoap_GetSubTransactions_input
    output = IIJPPServiceSoap_GetSubTransactions_output


class IIJPPServiceSoap_GetSubTransactionsBySubsidy:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetSubTransactionsBySubsidy"
    input = IIJPPServiceSoap_GetSubTransactionsBySubsidy_input
    output = IIJPPServiceSoap_GetSubTransactionsBySubsidy_output


class IIJPPServiceSoap_GetVozniRediZaPrevoznika:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetVozniRediZaPrevoznika"
    input = IIJPPServiceSoap_GetVozniRediZaPrevoznika_input
    output = IIJPPServiceSoap_GetVozniRediZaPrevoznika_output


class IIJPPServiceSoap_GetWhiteList:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetWhiteList"
    input = IIJPPServiceSoap_GetWhiteList_input
    output = IIJPPServiceSoap_GetWhiteList_output


@dataclass
class IIJPPServiceSoap_IdentifyTransactionParameters_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_IdentifyTransactionParameters_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        IdentifyTransactionParametersResponse: Optional['IdentifyTransactionParametersResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_IdentifyTransactionParameters_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_RegistrationTerminal:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/RegistrationTerminal"
    input = IIJPPServiceSoap_RegistrationTerminal_input
    output = IIJPPServiceSoap_RegistrationTerminal_output


@dataclass
class IIJPPServiceSoap_SetDelovnaNalogaZaPrevoznika_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetDelovnaNalogaZaPrevoznika_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetDelovnaNalogaZaPrevoznika: Optional['SetDelovnaNalogaZaPrevoznika'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_SpremeniVeljavnostDelovneNaloge_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SpremeniVeljavnostDelovneNaloge_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SpremeniVeljavnostDelovneNaloge: Optional['SpremeniVeljavnostDelovneNaloge'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_UpdateCardPassengerStatus_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_UpdateCardPassengerStatus_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        UpdateCardPassengerStatus: Optional['UpdateCardPassengerStatus'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class ProcessTransactions:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['ProcessTransactionsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class ProcessTransactionsRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['ProcessTransactionsRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetExecutableList:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetExecutableListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetExecutableListResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetExecutableListResult: Optional['SetExecutableListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetExecutableListRest:
    class Meta:
        namespace = "http://tempuri.org/"

    messageContext: Optional['wsMessageContext'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    request: Optional['SetExecutableListRequest'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class SetExecutableListRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    SetExecutableListRestResult: Optional['SetExecutableListResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class Tariff:
    class Meta:
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iServiceProviderId: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    iTariffFormat: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mServiceProviderTariffData: Optional['ArrayOfServiceProviderTariff'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    mTariffLocationSubLocations: Optional['ArrayOfTariffLocationSubLocations'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sServiceProviderName: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetDuplicateDataResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetDuplicateDataResult: Optional['GetDuplicateDataResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetDuplicateDataRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetDuplicateDataRestResult: Optional['GetDuplicateDataResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


class IIJPPServiceSoap_GetCardPassengerStatus:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetCardPassengerStatus"
    input = IIJPPServiceSoap_GetCardPassengerStatus_input
    output = IIJPPServiceSoap_GetCardPassengerStatus_output


@dataclass
class IIJPPServiceSoap_GetCardProducts_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCardProducts_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCardProductsResponse: Optional['GetCardProductsResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetCardProducts_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetCasovniRezimi_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCasovniRezimi_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetCasovniRezimiResponse: Optional['GetCasovniRezimiResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetCasovniRezimi_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetCone_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetCone_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetConeResponse: Optional['GetConeResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetCone_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetExecutableList_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetExecutableList_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetExecutableListResponse: Optional['GetExecutableListResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetExecutableList_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetLinijskiOdseki_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetLinijskiOdseki_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetLinijskiOdsekiResponse: Optional['GetLinijskiOdsekiResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetLinijskiOdseki_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetPostajalisca:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetPostajalisca"
    input = IIJPPServiceSoap_GetPostajalisca_input
    output = IIJPPServiceSoap_GetPostajalisca_output


class IIJPPServiceSoap_GetPostajneTocke:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetPostajneTocke"
    input = IIJPPServiceSoap_GetPostajneTocke_input
    output = IIJPPServiceSoap_GetPostajneTocke_output


class IIJPPServiceSoap_GetPostajneTockeZaPrevoznika:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetPostajneTockeZaPrevoznika"
    input = IIJPPServiceSoap_GetPostajneTockeZaPrevoznika_input
    output = IIJPPServiceSoap_GetPostajneTockeZaPrevoznika_output


@dataclass
class IIJPPServiceSoap_GetRezimiZaPrevoznika_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetRezimiZaPrevoznika_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetRezimiZaPrevoznikaResponse: Optional['GetRezimiZaPrevoznikaResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetRezimiZaPrevoznika_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetRezimi_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetRezimi_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetRezimiResponse: Optional['GetRezimiResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetRezimi_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetTariffTypeTransitionMatrix_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetTariffTypeTransitionMatrix_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetTariffClassTransitionMatrixResponse: Optional['GetTariffTypeTransitionMatrixResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetTariffTypeTransitionMatrix_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetTransactions_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetTransactions_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetTransactionsResponse: Optional['GetTransactionsResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetTransactions_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


@dataclass
class IIJPPServiceSoap_GetVozniRediIndexZaPrevoznika_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetVozniRediIndexZaPrevoznika_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetVozniRediIndexZaPrevoznikaResponse: Optional['GetVozniRediIndexZaPrevoznikaResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetVozniRediIndexZaPrevoznika_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_IdentifyTransactionParameters:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/IdentifyTransactionParameters"
    input = IIJPPServiceSoap_IdentifyTransactionParameters_input
    output = IIJPPServiceSoap_IdentifyTransactionParameters_output


@dataclass
class IIJPPServiceSoap_ProcessTransactions_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_ProcessTransactions_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        ProcessTransactions: Optional['ProcessTransactions'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


class IIJPPServiceSoap_SetDelovnaNalogaZaPrevoznika:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SetDelovnaNalogaZaPrevoznika"
    input = IIJPPServiceSoap_SetDelovnaNalogaZaPrevoznika_input
    output = IIJPPServiceSoap_SetDelovnaNalogaZaPrevoznika_output


@dataclass
class IIJPPServiceSoap_SetExecutableList_input:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetExecutableList_input.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetExecutableList: Optional['SetExecutableList'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )


@dataclass
class IIJPPServiceSoap_SetExecutableList_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_SetExecutableList_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        SetExecutableListResponse: Optional['SetExecutableListResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_SetExecutableList_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_SpremeniVeljavnostDelovneNaloge:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SpremeniVeljavnostDelovneNaloge"
    input = IIJPPServiceSoap_SpremeniVeljavnostDelovneNaloge_input
    output = IIJPPServiceSoap_SpremeniVeljavnostDelovneNaloge_output


class IIJPPServiceSoap_UpdateCardPassengerStatus:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/UpdateCardPassengerStatus"
    input = IIJPPServiceSoap_UpdateCardPassengerStatus_input
    output = IIJPPServiceSoap_UpdateCardPassengerStatus_output


@dataclass
class GetTariffResponse_1:
    class Meta:
        name = "GetTariffResponse"
        namespace = "http://schemas.datacontract.org/2004/07/WCF_IJPPService.Classes"

    iResultCode: Optional['int'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )
    mTariffData: Optional['Tariff'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )
    sResultDescription: Optional['str'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


class IIJPPServiceSoap_GetCardProducts:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetCardProducts"
    input = IIJPPServiceSoap_GetCardProducts_input
    output = IIJPPServiceSoap_GetCardProducts_output


class IIJPPServiceSoap_GetCasovniRezimi:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetCasovniRezimi"
    input = IIJPPServiceSoap_GetCasovniRezimi_input
    output = IIJPPServiceSoap_GetCasovniRezimi_output


class IIJPPServiceSoap_GetCone:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetCone"
    input = IIJPPServiceSoap_GetCone_input
    output = IIJPPServiceSoap_GetCone_output


@dataclass
class IIJPPServiceSoap_GetDuplicateData_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetDuplicateData_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetDuplicateDataResponse: Optional['GetDuplicateDataResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetDuplicateData_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetExecutableList:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetExecutableList"
    input = IIJPPServiceSoap_GetExecutableList_input
    output = IIJPPServiceSoap_GetExecutableList_output


class IIJPPServiceSoap_GetLinijskiOdseki:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetLinijskiOdseki"
    input = IIJPPServiceSoap_GetLinijskiOdseki_input
    output = IIJPPServiceSoap_GetLinijskiOdseki_output


class IIJPPServiceSoap_GetRezimi:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetRezimi"
    input = IIJPPServiceSoap_GetRezimi_input
    output = IIJPPServiceSoap_GetRezimi_output


class IIJPPServiceSoap_GetRezimiZaPrevoznika:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetRezimiZaPrevoznika"
    input = IIJPPServiceSoap_GetRezimiZaPrevoznika_input
    output = IIJPPServiceSoap_GetRezimiZaPrevoznika_output


class IIJPPServiceSoap_GetTariffTypeTransitionMatrix:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetTariffClassTransitionMatrix"
    input = IIJPPServiceSoap_GetTariffTypeTransitionMatrix_input
    output = IIJPPServiceSoap_GetTariffTypeTransitionMatrix_output


class IIJPPServiceSoap_GetTransactions:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetTransactions"
    input = IIJPPServiceSoap_GetTransactions_input
    output = IIJPPServiceSoap_GetTransactions_output


class IIJPPServiceSoap_GetVozniRediIndexZaPrevoznika:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetVozniRediIndexZaPrevoznika"
    input = IIJPPServiceSoap_GetVozniRediIndexZaPrevoznika_input
    output = IIJPPServiceSoap_GetVozniRediIndexZaPrevoznika_output


class IIJPPServiceSoap_ProcessTransactions:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/ProcessTransactions"
    input = IIJPPServiceSoap_ProcessTransactions_input
    output = IIJPPServiceSoap_ProcessTransactions_output


class IIJPPServiceSoap_SetExecutableList:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/SetExecutableList"
    input = IIJPPServiceSoap_SetExecutableList_input
    output = IIJPPServiceSoap_SetExecutableList_output


@dataclass
class GetTariffResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetTariffResult: Optional['GetTariffResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


@dataclass
class GetTariffRestResponse:
    class Meta:
        namespace = "http://tempuri.org/"

    GetTariffRestResult: Optional['GetTariffResponse_1'] = field(
        default=None,
        metadata={
            "type": "Element",
            "nillable": True,
        }
    )


class IIJPPServiceSoap_GetDuplicateData:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetDuplicateData"
    input = IIJPPServiceSoap_GetDuplicateData_input
    output = IIJPPServiceSoap_GetDuplicateData_output


@dataclass
class IIJPPServiceSoap_GetTariff_output:
    class Meta:
        name = "Envelope"
        namespace = "http://schemas.xmlsoap.org/soap/envelope/"
        target_namespace = "http://tempuri.org/"

    Body: Optional['"IIJPPServiceSoap_GetTariff_output.Body"'] = field(
        default=None,
        metadata={
            "type": "Element",
        }
    )

    @dataclass
    class Body:
        GetTariffResponse: Optional['GetTariffResponse'] = field(
            default=None,
            metadata={
                "type": "Element",
                "namespace": "http://tempuri.org/",
            }
        )
        Fault: Optional['"IIJPPServiceSoap_GetTariff_output.Body.Fault"'] = field(
            default=None,
            metadata={
                "type": "Element",
            }
        )

        @dataclass
        class Fault:
            faultcode: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultstring: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            faultactor: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )
            detail: Optional['str'] = field(
                default=None,
                metadata={
                    "type": "Element",
                    "namespace": "",
                }
            )


class IIJPPServiceSoap_GetTariff:
    URI = "#SOAPEndPoint_policy"
    style = "document"
    location = "https://b2b.ncup.si/data/b2b.ijpp.ijppservice"
    transport = "http://schemas.xmlsoap.org/soap/http"
    soapAction = "http://tempuri.org/IIJPPServiceSoap/GetTariff"
    input = IIJPPServiceSoap_GetTariff_input
    output = IIJPPServiceSoap_GetTariff_output
