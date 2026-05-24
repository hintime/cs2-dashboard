#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ECOSteam API 签名模块（共享）
被 update.py / recommend.py 共用
"""
import os, json, base64
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

_eco_key = None


def get_eco_key(data_dir=None):
    """加载 ECO RSA 私钥。优先读环境变量，其次读本地文件。"""
    global _eco_key
    if _eco_key is not None:
        return _eco_key
    key_b64 = os.environ.get('ECO_PRIVATE_KEY_B64')
    if not key_b64:
        if data_dir:
            key_path = os.path.join(data_dir, 'eco_private_key.txt')
        else:
            key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'eco_private_key.txt')
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                key_b64 = f.read().strip()
        else:
            raise FileNotFoundError('ECO private key not found')
    pem = '-----BEGIN RSA PRIVATE KEY-----\n' + key_b64 + '\n-----END RSA PRIVATE KEY-----'
    _eco_key = RSA.import_key(pem)
    return _eco_key


def sign_eco(params, eco_key=None):
    """对 ECOSteam API 参数签名。"""
    if eco_key is None:
        eco_key = get_eco_key()
    sorted_params = sorted(params.items(), key=lambda x: x[0].lower())
    parts = []
    for k, v in sorted_params:
        if v is None or v == '':
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v, separators=(',', ':'), ensure_ascii=False)
        parts.append(f'{k}={v}')
    sign_str = '&'.join(parts)
    h = SHA256.new(sign_str.encode('utf-8'))
    return base64.b64encode(pkcs1_15.new(eco_key).sign(h)).decode()
