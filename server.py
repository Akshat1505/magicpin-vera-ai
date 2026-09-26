from __future__ import annotations
import os, json, time, uuid, re
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bot import compose

app=FastAPI(title="VERA Growth Engine", version="1.0.0")
START=time.time()
STORE={"category":{},"merchant":{},"customer":{},"trigger":{}}
CONVS={}
SENT=set()

class ContextPush(BaseModel):
    scope:str; context_id:str; version:int=1; payload:dict; delivered_at:str|None=None
class TickReq(BaseModel):
    now:str; available_triggers:list[str]=[]
class ReplyReq(BaseModel):
    conversation_id:str; merchant_id:str; customer_id:str|None=None; from_role:str; message:str; received_at:str|None=None; turn_number:int=1

def _get(scope,id): return STORE.get(scope,{}).get(id,{}).get("payload")
def _category_for(m): return STORE["category"].get(m.get("category_slug"),{}).get("payload",{})
def _mkconv(m,c,t): return f"conv_{m.get('merchant_id')}_{(c or {}).get('customer_id') or 'merchant'}_{t.get('id')}"

def _validate(scope,payload):
    if scope not in STORE: raise HTTPException(400,detail={"accepted":False,"reason":"invalid_scope"})
    if not isinstance(payload,dict): raise HTTPException(400,detail={"accepted":False,"reason":"invalid_payload"})

@app.post('/v1/context')
def context(req:ContextPush):
    _validate(req.scope,req.payload)
    old=STORE[req.scope].get(req.context_id)
    if old and req.version < old["version"]:
        return {"accepted":False,"reason":"stale_version","current_version":old["version"]}
    if old and req.version == old["version"]: return {"accepted":True,"ack_id":"ack_idempotent","stored_at":req.delivered_at}
    STORE[req.scope][req.context_id]={"version":req.version,"payload":req.payload,"stored_at":req.delivered_at or time.time()}
    return {"accepted":True,"ack_id":"ack_"+uuid.uuid4().hex[:10],"stored_at":req.delivered_at or time.time()}

@app.post('/v1/tick')
def tick(req:TickReq):
    actions=[]
    for tid in req.available_triggers:
        tr=_get("trigger",tid)
        if not tr: continue
        mid=tr.get("merchant_id") or (tr.get("payload") or {}).get("merchant_id")
        m=_get("merchant",mid)
        if not m: continue
        cat=_category_for(m)
        cid=tr.get("customer_id") or (tr.get("payload") or {}).get("customer_id")
        c=_get("customer",cid) if cid else None
        key=tr.get("suppression_key")
        if key and key in SENT: continue
        out=compose(cat,m,tr,c)
        conv=_mkconv(m,c,tr)
        if conv in CONVS: continue
        CONVS[conv]={"merchant_id":mid,"customer_id":cid,"trigger_id":tid,"history":[{"role":"vera","body":out["body"]}]}
        actions.append({"conversation_id":conv,"merchant_id":mid,"customer_id":cid,"send_as":out["send_as"],"trigger_id":tid,"template_name":"vera_contextual_v1","template_params":[],"body":out["body"],"cta":out["cta"],"suppression_key":out["suppression_key"],"rationale":out["rationale"]})
        if key: SENT.add(key)
        if len(actions)>=20: break
    return {"actions":actions}

AUTO_PAT=["thank you for contacting","thanks for contacting","we have received your message","will get back to you","auto reply","thank you for reaching out"]
STOP_PAT=["stop","don't message","do not message","not interested","no thanks","unsubscribe"]
YES_PAT=["yes","y","go ahead","do it","let's do it","lets do it","send it","send me","join","sounds good","proceed","confirm"]

def _classify(msg):
    s=msg.lower().strip()
    if any(x in s for x in STOP_PAT): return "stop"
    if any(x in s for x in AUTO_PAT): return "auto"
    if any(x in s for x in YES_PAT): return "yes"
    if "when" in s or "how much" in s or "what" in s or "why" in s: return "question"
    return "other"

@app.post('/v1/reply')
def reply(req:ReplyReq):
    conv=CONVS.setdefault(req.conversation_id,{"merchant_id":req.merchant_id,"customer_id":req.customer_id,"history":[]})
    conv["history"].append({"role":req.from_role,"body":req.message})
    typ=_classify(req.message)
    if typ=="stop": return {"action":"end","rationale":"Explicit opt-out/not-interested signal; stop the conversation without further persuasion."}
    if typ=="auto":
        repeats=sum(1 for x in conv["history"] if x.get("role")==req.from_role and x.get("body","").strip().lower()==req.message.strip().lower())
        if repeats>=2: return {"action":"end","rationale":"Repeated canned/auto-replies detected; end the conversation rather than continue messaging."}
        return {"action":"wait","wait_seconds":900,"rationale":"Reply resembles a WhatsApp canned acknowledgement; wait for a substantive response."}
    if typ=="yes":
        body="Done — I’ll move to the next step using the context you already approved. I won’t re-qualify unless something essential is missing."
        conv["history"].append({"role":"vera","body":body})
        return {"action":"send","body":body,"cta":"open_ended","rationale":"Merchant expressed action intent, so transition directly from pitch to execution."}
    if typ=="question":
        body="I can answer that from the current merchant context. Tell me the specific detail you want checked, and I’ll use the numbers/offer already on file rather than guessing."
        conv["history"].append({"role":"vera","body":body})
        return {"action":"send","body":body,"cta":"open_ended","rationale":"Answer request without fabricating information unavailable in the pushed context."}
    return {"action":"wait","wait_seconds":900,"rationale":"No clear action intent detected; avoid unnecessary follow-up."}

@app.get('/v1/healthz')
def healthz():
    return {"status":"ok","uptime_seconds":int(time.time()-START),"contexts_loaded":{k:len(v) for k,v in STORE.items()}}

@app.get('/v1/metadata')
def metadata():
    return {"name":"VERA Growth Engine","team_name":os.getenv("TEAM_NAME","VERA Builder"),"team_members":[],"model":"deterministic-context-engine","approach":"context-grounded routing + category strategy + deterministic composer + reply state machine","contact_email":os.getenv("CONTACT_EMAIL",""),"version":"1.0.0"}
