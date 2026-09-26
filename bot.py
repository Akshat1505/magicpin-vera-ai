"""VERA merchant-growth assistant: deterministic, context-grounded decision engine."""
from __future__ import annotations
from datetime import datetime
import re
from typing import Any


def _pct(x):
    try: return f"{abs(float(x))*100:.0f}%"
    except: return str(x)

def _name(m):
    return (m.get("identity") or {}).get("owner_first_name") or (m.get("identity") or {}).get("name", "there")

def _biz(m): return (m.get("identity") or {}).get("name", "your business")
def _cat(c,m): return c.get("slug") or m.get("category_slug") or "business"
def _active_offer(m):
    for o in m.get("offers", []):
        if str(o.get("status","")).lower() == "active": return o.get("title")
    return None

def _digest(c, trig):
    p=trig.get("payload") or {}; wanted=p.get("top_item_id")
    items=c.get("digest") or []
    if wanted:
        for x in items:
            if x.get("id")==wanted: return x
    return items[0] if items else None

def _locality(m):
    i=m.get("identity") or {}; return i.get("locality") or i.get("city") or "your area"

def _hi(m, customer=None):
    langs=(customer or {}).get("identity",{}).get("language_pref") or ",".join((m.get("identity") or {}).get("languages",[]))
    return "hi" in str(langs).lower() or "mix" in str(langs).lower()

def _facts(category, merchant, trigger, customer=None):
    p=trigger.get("payload") or {}; perf=merchant.get("performance") or {}
    return {
      "owner":_name(merchant),"business":_biz(merchant),"city":(merchant.get("identity") or {}).get("city"),
      "locality":_locality(merchant),"category":_cat(category,merchant),"offer":_active_offer(merchant),
      "rating":(category.get("peer_stats") or {}).get("avg_rating"),"peer_ctr":(category.get("peer_stats") or {}).get("avg_ctr"),
      "views":perf.get("views"),"calls":perf.get("calls"),"ctr":perf.get("ctr"),"p":p,
      "customer":customer or {}
    }

def _merchant_msg(category, merchant, trigger, customer=None):
    k=trigger.get("kind",""); f=_facts(category,merchant,trigger,customer); p=f["p"]; n=f["owner"]; cat=f["category"]
    offer=f["offer"]
    # Planning/action intent should execute, not re-qualify.
    if k in {"active_planning_intent","campaign_intent","kids_yoga_program_drafting","drafting_intent"}:
        topic=p.get("intent_topic") or p.get("topic") or "the plan"
        last=p.get("merchant_last_message")
        return (f"{n}, got it — I’ll turn the {topic.replace('_',' ')} into a concrete draft using your current context. "
                + (f"You said: ‘{last}’. " if last else "") + "Reply YES and I’ll prepare the copy and next steps.", "binary", f"intent:{trigger.get('id')}")
    if k=="research_digest":
        d=_digest(category,trigger)
        if d:
            src=d.get("source"); title=d.get("title"); extra=[]
            if d.get("trial_n"): extra.append(f"n={d['trial_n']}")
            seg=d.get("patient_segment")
            detail=(f" ({', '.join(extra)})" if extra else "")
            return (f"{n}, {src} has a new item: “{title}”{detail}. "
                    f"It’s relevant to your {cat} practice and gives you a concrete patient-content angle. Want me to turn the finding into a 60-sec WhatsApp/GBP post?",
                    "open_ended", trigger.get("suppression_key"))
    if k in {"regulation_change","compliance_alert","compliance_update"}:
        d=_digest(category,trigger); title=d.get("title") if d else p.get("title","a compliance update"); src=d.get("source") if d else p.get("source")
        deadline=p.get("deadline_iso") or p.get("deadline")
        tail=f" Deadline: {deadline}." if deadline else ""
        return (f"{n}, {src + ' has ' if src else ''}a compliance update: “{title}”.{tail} "
                f"I can turn the requirement into a short checklist for {f['business']} — want me to draft it?", "binary", trigger.get("suppression_key"))
    if k in {"perf_dip","seasonal_perf_dip"}:
        metric=p.get("metric","performance"); delta=p.get("delta_pct", (merchant.get("performance") or {}).get("delta_7d",{}).get(metric+"_pct"))
        if k=="seasonal_perf_dip" and p.get("is_expected_seasonal"):
            note=p.get("season_note","seasonal")
            return (f"{n}, {metric} is down {_pct(delta)} over {p.get('window','7d')}, but this is flagged as expected {note.replace('_',' ')} seasonality. "
                    f"Rather than push a generic discount, want me to suggest one category-specific acquisition angle?", "binary", trigger.get("suppression_key"))
        base=p.get("vs_baseline")
        base_txt=f" vs {base} baseline" if base is not None else ""
        return (f"{n}, your {metric} is down {_pct(delta)}{base_txt} over {p.get('window','7d')}. "
                f"That’s the clearest issue in the current signals. Want me to draft one low-effort fix using your existing offer/context?", "binary", trigger.get("suppression_key"))
    if k in {"perf_spike","milestone_reached"}:
        metric=p.get("metric","performance"); val=p.get("value_now")
        if val is not None:
            return (f"{n}, quick win: you’re at {val} on {metric.replace('_',' ')} and the milestone is close. "
                    f"Want me to draft the next GBP/WhatsApp post so we can use the momentum?", "binary", trigger.get("suppression_key"))
        delta=p.get("delta_pct")
        return (f"{n}, your {metric} is up {_pct(delta)} in the current window. "
                f"Want me to turn the spike into one concrete growth action?", "binary", trigger.get("suppression_key"))
    if k in {"renewal_due","renewal_due_soon"}:
        days=p.get("days_remaining") or (merchant.get("subscription") or {}).get("days_remaining")
        amt=p.get("renewal_amount")
        cost=f" at ₹{amt:,}" if isinstance(amt,(int,float)) else ""
        return (f"{n}, your {((merchant.get('subscription') or {}).get('plan') or 'plan')} renewal is due in {days} days{cost}. "
                f"Want me to walk you through the renewal now?", "binary", trigger.get("suppression_key"))
    if k in {"unverified_gbp"}:
        return (f"{n}, {f['business']} is still unverified on Google Business Profile. "
                f"That’s a concrete profile gap; want me to give you the exact verification steps?", "binary", trigger.get("suppression_key"))
    if k in {"ipl_match_today","festival_upcoming","local_news_event","weather_heatwave"}:
        event=p.get("match") or p.get("festival") or p.get("event") or p.get("headline") or k.replace('_',' ')
        when=p.get("match_time_iso") or p.get("date") or p.get("days_until")
        if k=="ipl_match_today" and not p.get("is_weeknight",True):
            return (f"{n}, {event} is at {when} today in {p.get('city',f['city'])}. Because it’s a weekend, I wouldn’t push a generic match discount. "
                    f"Your current offer is {offer or 'not specified'}; want me to draft a match-night post around the offer you already have?", "binary", trigger.get("suppression_key"))
        return (f"{n}, {event} is the timely signal right now{f' ({when})' if when else ''}. "
                f"Want me to draft one {cat}-specific post using {offer or 'your current offer'}?", "binary", trigger.get("suppression_key"))
    if k in {"competitor_opened"}:
        dist=p.get("distance_km") or p.get("distance")
        name=p.get("competitor_name")
        detail=(f" {name} opened {dist}km away." if name and dist else f" A nearby competitor signal just appeared in {f['locality']}.")
        return (f"{n},{detail} Rather than react with a blanket discount, want me to compare the signal with your current profile/offers and draft one response?", "binary", trigger.get("suppression_key"))
    if k in {"review_theme_emerged"}:
        theme=p.get("theme","review theme"); count=p.get("occurrences_30d")
        return (f"{n}, {count or 'Several'} reviews in the last 30 days mention “{theme.replace('_',' ')}” and the trend is {p.get('trend','rising')}. "
                f"Want me to draft a response/process fix around that theme?", "binary", trigger.get("suppression_key"))
    if k in {"curious_ask_due","scheduled_recurring"}:
        return (f"{n}, quick one: what’s the service customers have been asking for most this week at {f['business']}? "
                f"Tell me the service and I’ll turn it into a concrete growth idea.", "open_ended", trigger.get("suppression_key"))
    if k in {"dormant_with_vera","dormancy_glamour","winback_eligible"}:
        days=p.get("days_since_expiry") or 14
        return (f"{n}, it’s been {days} days since the last active Vera touch. I spotted a current signal worth acting on rather than sending a generic promo. "
                f"Want me to surface the one opportunity I’d start with?", "binary", trigger.get("suppression_key"))
    # Generic safe fallback, still grounded.
    return (f"{n}, I spotted a {k.replace('_',' ')} signal for {f['business']}. Want me to turn it into one concrete next step?", "binary", trigger.get("suppression_key"))

def _customer_msg(category, merchant, trigger, customer):
    p=trigger.get("payload") or {}; f=_facts(category,merchant,trigger,customer); c=customer or {}; ci=c.get("identity") or {}; name=ci.get("name","there"); k=trigger.get("kind","")
    mix=_hi(merchant,customer)
    prefix="Namaste" if mix else "Hi"
    if k in {"recall_due","customer_lapsed_soft","appointment_tomorrow"}:
        due=p.get("due_date") or p.get("appointment_date") or p.get("date")
        services=(c.get("relationship") or {}).get("services_received") or ["your visit"]
        service=p.get("service_due") or services[-1]
        slots=p.get("available_slots") or []
        slot=slots[0].get("label") if slots and isinstance(slots[0],dict) else None
        s=f" {slot} is available." if slot else ""
        body=(f"{prefix} {name}, {f['business']} here. Your {service.replace('_',' ')} follow-up is due"
              f"{f' by {due}' if due else ''}.{s} "
              f"Would you like me to hold a convenient slot? Reply YES and I’ll take care of the next step.")
        return body,"binary",trigger.get("suppression_key")
    if k in {"chronic_refill_due","chronic_refill_grandfather"}:
        meds=p.get("medicines") or p.get("molecules") or []
        medtxt=", ".join(meds) if isinstance(meds,list) else str(meds)
        due=p.get("due_date") or p.get("run_out_date")
        offer=f["offer"] or "your current pharmacy service"
        return (f"{prefix} {name}, {f['business']} here. Your regular refill for {medtxt or 'your medicines'} is due"
                f"{f' on {due}' if due else ''}. {offer} is available. Reply CONFIRM if you’d like us to prepare it, or STOP if you don’t want reminders.", "binary", trigger.get("suppression_key"))
    if k in {"wedding_package_followup"}:
        wd=p.get("wedding_date")
        return (f"{prefix} {name}, {f['business']} here. Your wedding is on {wd}, and your next prep window is now open. "
                f"We can pick up from your completed trial. Reply YES and we’ll share the 30-day prep plan.", "binary", trigger.get("suppression_key"))
    return (f"{prefix} {name}, {f['business']} here. We have a relevant update for you. Reply YES if you’d like the next step, or STOP to opt out.", "binary", trigger.get("suppression_key"))

def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    """Return the required composition contract. Fully deterministic and context-grounded."""
    if customer or trigger.get("scope")=="customer":
        body,cta,key=_customer_msg(category,merchant,trigger,customer)
        send_as="merchant_on_behalf"
    else:
        body,cta,key=_merchant_msg(category,merchant,trigger,customer)
        send_as="vera"
    rationale=f"Selected {trigger.get('kind','signal').replace('_',' ')} as the current action because it is directly supported by the supplied trigger and merchant/category context."
    return {"body":body,"cta":cta,"send_as":send_as,"suppression_key":key,"rationale":rationale}

# Backwards-friendly alias
