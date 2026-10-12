from base64 import b64encode
import re

import ijpp
from xsdata.formats.dataclass.client import Client
import requests


class IJPPClient:
    headers: dict

    def __init__(self, apikey=None, username=None, password=None):
        if username and password:
            creds = b64encode(f'{username}:{password}'.encode('ascii'))
            self.headers = {
                'Authorization': 'Basic ' + creds.decode('ascii'),
            }
        elif apikey:
            self.headers = {
                'Authorization': 'bearer ' + apikey,
            }

    def request(self, req: object):
        name = self.get_name(req)
        req = self.make_request(req, name=name)
        client = self.make_client(req, name=name)
        data = client.prepare_payload(req)
        action = 'http://tempuri.org/IIJPPServiceSoap/' + name
        soap_headers = f'<soapenv:Header xmlns:wsa="http://www.w3.org/2005/08/addressing"><wsa:Action>{action}</wsa:Action></soapenv:Header>'
        data = data.replace('<Body>', soap_headers + '<Body>')
        data = data.replace('<Body>', '<soapenv:Body>').replace('</Body>', '</soapenv:Body>')
        data = data.replace('http://schemas.xmlsoap.org/soap/envelope/', 'http://www.w3.org/2003/05/soap-envelope')
        headers = self.headers | {'Content-Type': f'application/soap+xml;charset=UTF-8;action="{action}"'}
        
        rsp = requests.post(client.config.location, data=data, headers=headers)
        response = rsp.content
        
        response = response.replace(b'http://www.w3.org/2003/05/soap-envelope', b'http://schemas.xmlsoap.org/soap/envelope/')
        response = response.replace(b's:Body', b'Body')
        response = re.sub(b'<s:Header.+/s:Header>', b'', response)
        resp = client.parser.from_bytes(response, client.config.output)
        r = getattr(getattr(resp.Body, name + 'Response'), name + 'Result')
        assert r.iResultCode == 0, r
        return r

    def get_name(self, req: object):
        name = type(req).__name__
        assert name.endswith('Request'), 'You may only use ...Request objects'
        name = name[0:-7]
        return name

    def make_request(self, req: object, name=None):
        if not name:
            name = self.get_name(req)
        SoapInput = getattr(ijpp, 'IIJPPServiceSoap_' + name + '_input')
        Service = getattr(ijpp, name)
        r = SoapInput(
            Body=SoapInput.Body(
                Service(
                    ijpp.wsMessageContext(
                        lRequestId=12345
                    ),
                    req,
                )
            )
        )
        return r

    def make_client(self, req: object, name):
        Service = getattr(ijpp, 'IIJPPServiceSoap_' + name)
        client = Client.from_service(Service)
        return client


#client = IJPPClient(
#    username='----',
#    password='---',
#)
#r = client.request(ijpp.GetCardRequest(
#    lCUID=36114536546845700
#))

#r = client.request(ijpp.GetPostajaliscaRequest())
#postaje = r.postajalisca.Postajalisce

#mb = [p for p in postaje if "Maribor AP" in p.ime]
#lj = [p for p in postaje if "Ljubljana AP" in p.ime]




print(r)
