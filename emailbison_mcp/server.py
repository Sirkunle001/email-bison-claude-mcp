"""
Email Bison MCP Server
- Robust HTTP (retries, previews, JSON/HTML safety, 422 detail, last_http surfacing)
- Replies (adaptive filters + legacy fallback)
- Stats fallbacks (POST/GET/POST {})
- Sequence steps v1.1 → legacy fallback
- Endpoints aligned to EmailBison docs/collection:
  * POST /api/campaigns (create_campaign)
  * POST /api/campaigns/:id/leads/attach-leads (attach_leads)
  * POST /api/campaigns/:id/leads/attach-lead-list (attach_lead_list)
  * POST /api/campaigns/:id/leads/stop-future-emails (stop_future_emails)
  * GET  /api/campaign-events/stats (campaign_events_stats)
  * GET  /api/sender-emails (list_email_accounts)
  * GET  /api/warmup/sender-emails (list_warmup_accounts)
  * GET  /api/warmup/sender-emails/:senderEmailId (warmup_account_details)
  * PATCH /api/warmup/sender-emails/enable|disable|update-daily-warmup-limits
  * raw_request tool for quick endpoint probing
"""

import asyncio, json, os, re, sys
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
import mcp.server.stdio
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types

# -------------------- Logging --------------------
def log_error(msg): print(f"ERROR: {msg}", file=sys.stderr, flush=True)
def log_debug(msg):
    if True:  # flip to False to quiet logs
        print(f"DEBUG: {msg}", file=sys.stderr, flush=True)

# -------------------- Setup ----------------------
load_dotenv()
server = Server("email-bison")

def _is_date(s: Optional[str]) -> bool:
    return bool(s and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))

# -------------------- Client ---------------------
class EmailBisonClient:
    FOLDER_MAP = {"inbox":"Inbox","sent":"Sent","spam":"Spam","bounced":"Bounced"}

    def __init__(self, api_key: str, base_url: Optional[str]=None):
        self.api_key = api_key or ""
        self.base_url = (base_url or os.getenv("EMAILBISON_BASE_URL") or "https://send.highticket.agency").rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "EmailBison-MCP/0.3",
        }
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0, read=20.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
        self.last_http: Dict[str, Any] = {
            "url": None, "method": None, "status": None, "content_type": None,
            "request_params": None, "request_json": None, "response_preview": None,
        }

    # ---------- Utils ----------
    @staticmethod
    def _to_query(params: Dict) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        def put(prefix: str, val: Any):
            if isinstance(val, list):
                for i, v in enumerate(val): put(f"{prefix}[{i}]", v)
            elif isinstance(val, dict):
                for k, v in val.items(): put(f"{prefix}[{k}]", v)
            elif val is not None:
                out.append((prefix, str(val)))
        for k, v in (params or {}).items():
            if isinstance(v, list):
                for i, item in enumerate(v): put(f"{k}[{i}]", item)
            elif isinstance(v, dict):
                for kk, vv in v.items(): put(f"{k}[{kk}]", vv)
            elif v is not None:
                out.append((k, str(v)))
        return out

    async def _request_with_retries(self, method: str, endpoint: str, *, params=None, json_body=None, max_retries=3) -> httpx.Response:
        url = f"{self.base_url}{endpoint}"
        attempt, last_exc = 0, None
        while attempt <= max_retries:
            try:
                log_debug(f"{method} {url} (attempt {attempt+1})")
                r = await self._client.request(method, url, headers=self.headers, params=params, json=json_body)
                log_debug(f"Status: {r.status_code}")
                if r.status_code in (429, 500, 502, 503, 504):
                    attempt += 1
                    delay = min(2 ** attempt, 10) + attempt*0.1
                    log_debug(f"Retryable {r.status_code}; sleep {delay:.1f}s")
                    await asyncio.sleep(delay); continue
                return r
            except httpx.RequestError as e:
                last_exc = e; attempt += 1
                delay = min(2 ** attempt, 10) + attempt*0.1
                log_debug(f"Transport {e!r}; sleep {delay:.1f}s")
                await asyncio.sleep(delay)
        if last_exc: raise last_exc
        raise RuntimeError("Request failed after retries")

    async def make_request(self, method: str, endpoint: str, params=None, data=None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        self.last_http.update({
            "url": url, "method": method, "status": None, "content_type": None,
            "request_params": params, "request_json": data, "response_preview": None
        })
        r = await self._request_with_retries(method, endpoint, params=params, json_body=data)
        ctype = r.headers.get("content-type", "")
        prev = r.text[:2000]
        self.last_http.update({"status": r.status_code, "content_type": ctype, "response_preview": prev})
        log_debug(f"CT {ctype} | Prev: {prev}")
        if r.status_code == 422:
            try: log_debug("422 detail: "+json.dumps(r.json(), indent=2)[:4000])
            except Exception: log_debug("422 raw: "+r.text[:4000])
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError:
            log_debug("Error body: "+r.text[:4000]); raise
        body = r.text.strip()
        if not body: return {}
        if "application/json" in ctype.lower() or body.startswith("{") or body.startswith("["):
            try: return r.json()
            except Exception as e:
                log_debug(f"JSON decode error on 200: {e!r}"); return {"raw": body}
        return {"raw": body}

    # ---------- Campaigns ----------
    async def get_campaigns(self, status: str=None, tag_ids: List[int]=None) -> Dict:
        params: Dict[str, Any] = {}
        if status: params["status"]=status
        if tag_ids: params["tag_ids"]=tag_ids
        first = await self.make_request("GET", "/api/campaigns", params=params)
        data, meta = first.get("data", []), first.get("meta", {}) or {}
        total_pages, current = meta.get("last_page", 1) or 1, meta.get("current_page", 1) or 1
        for page in range(current+1, total_pages+1):
            p = dict(params); p["page"]=page
            nxt = await self.make_request("GET", "/api/campaigns", params=p)
            data.extend(nxt.get("data", []))
        return {"data": data, "meta": {"total": len(data), "total_pages": total_pages}}

    async def get_campaign_details(self, campaign_id: int) -> Dict:
        return await self.make_request("GET", f"/api/campaigns/{campaign_id}")

    async def create_campaign(self, name: str, campaign_type: str="outbound", **kwargs) -> Dict:
        payload = {"name": name, "type": campaign_type}
        payload.update(kwargs or {})
        return await self.make_request("POST", "/api/campaigns", data=payload)

    # ---------- Stats & Sequence ----------
    async def get_campaign_stats(self, campaign_id: int, start_date: str=None, end_date: str=None) -> Dict:
        body = {}
        if _is_date(start_date): body["start_date"]=start_date
        if _is_date(end_date):   body["end_date"]=end_date
        try:
            return await self.make_request("POST", f"/api/campaigns/{campaign_id}/stats", data=body)
        except httpx.HTTPStatusError:
            pass
        q=[]
        if _is_date(start_date): q.append(("start_date", start_date))
        if _is_date(end_date):   q.append(("end_date", end_date))
        try:
            return await self.make_request("GET", f"/api/campaigns/{campaign_id}/stats", params=q or None)
        except httpx.HTTPStatusError:
            return await self.make_request("POST", f"/api/campaigns/{campaign_id}/stats", data={})

    async def get_sequence_steps(self, campaign_id: int) -> Dict:
        try:
            return await self.make_request("GET", f"/api/campaigns/v1.1/{campaign_id}/sequence-steps")
        except httpx.HTTPStatusError:
            return await self.make_request("GET", f"/api/campaigns/{campaign_id}/sequence-steps")

    # ---------- Replies (adaptive) ----------
    async def get_campaign_replies(self, campaign_id: int, status: Optional[str]=None, folder: Optional[str]=None) -> Dict:
        def build_filters(shape: str) -> Dict[str, Any]:
            f: Dict[str, Any] = {}
            if shape=="single_value": f["campaign_id"]={"value":campaign_id}
            elif shape=="array":      f["campaign_ids"]=[campaign_id]
            elif shape=="bare":       f["campaign_id"]=campaign_id
            elif shape=="array_value":f["campaign_ids"]={"value":[campaign_id]}
            elif shape=="value_array":f["campaign_id"]=[campaign_id]
            if folder and folder.lower()!="all":
                norm = self.FOLDER_MAP.get(folder.lower()); 
                if norm: f["folder"]={"value": norm}
            if status=="interested": f["interested"]={"value":1}
            elif status=="automated_reply": f["automated_reply"]={"value":1}
            elif status=="not_automated_reply": f["automated_reply"]={"value":0}
            return f

        async def fetch_global(params_list):
            params_list = list(params_list)+[("per_page","200")]
            first = await self.make_request("GET","/api/replies",params=params_list)
            data = (first.get("data") or []) if isinstance(first,dict) else []
            meta = (first.get("meta") or {}) if isinstance(first,dict) else {}
            last, cur = meta.get("last_page",1) or 1, meta.get("current_page",1) or 1
            for page in range(cur+1, last+1):
                nxt = await self.make_request("GET","/api/replies",params=params_list+[("page",str(page))])
                data.extend((nxt.get("data") or []) if isinstance(nxt,dict) else [])
            return {"data": data, "meta": {"total": len(data), "total_pages": last}}

        shapes = ["single_value","array","bare","array_value","value_array"]
        for shape in shapes:
            try:
                flt = {"filters": build_filters(shape)}
                return await fetch_global(self._to_query(flt))
            except Exception as e:
                log_debug(f"/api/replies shape {shape} failed: {e!r}")

        # Legacy per-campaign replies
        first = await self.make_request("GET", f"/api/campaigns/{campaign_id}/replies", params={"per_page": 200})
        data = (first.get("data") or []) if isinstance(first,dict) else []
        meta = (first.get("meta") or {}) if isinstance(first,dict) else {}
        last, cur = meta.get("last_page",1) or 1, meta.get("current_page",1) or 1
        for page in range(cur+1, last+1):
            nxt = await self.make_request("GET", f"/api/campaigns/{campaign_id}/replies", params={"page": page, "per_page": 200})
            data.extend((nxt.get("data") or []) if isinstance(nxt,dict) else [])
        # Optional client-side filter
        if status=="interested": data=[r for r in data if r.get("interested")]
        elif status=="automated_reply": data=[r for r in data if r.get("automated_reply")]
        elif status=="not_automated_reply": data=[r for r in data if not r.get("automated_reply")]
        if folder and folder.lower()!="all":
            want = self.FOLDER_MAP.get(folder.lower()); 
            if want: data=[r for r in data if r.get("folder")==want]
        return {"data": data, "meta": {"total": len(data), "total_pages": last}}

    # ---------- Leads (attach / list) ----------
    async def get_campaign_leads(self, campaign_id: int, filters: Dict=None) -> Dict:
        first = await self.make_request("GET", f"/api/campaigns/{campaign_id}/leads", params=filters or {})
        data, meta = (first.get("data", []) or []), (first.get("meta", {}) or {})
        last, cur = meta.get("last_page",1) or 1, meta.get("current_page",1) or 1
        for page in range(cur+1, last+1):
            nxt = await self.make_request("GET", f"/api/campaigns/{campaign_id}/leads", params={**(filters or {}), "page": page})
            data.extend(nxt.get("data", []) or [])
        return {"data": data, "meta": {"total": len(data), "total_pages": last}}

    async def attach_leads(self, campaign_id: int, lead_ids: List[int], allow_parallel_sending: bool=False) -> Dict:
        body = {"lead_ids": lead_ids, "allow_parallel_sending": allow_parallel_sending}
        return await self.make_request("POST", f"/api/campaigns/{campaign_id}/leads/attach-leads", data=body)

    async def attach_lead_list(self, campaign_id: int, lead_list_id: int, allow_parallel_sending: bool=False) -> Dict:
        body = {"lead_list_id": lead_list_id, "allow_parallel_sending": allow_parallel_sending}
        return await self.make_request("POST", f"/api/campaigns/{campaign_id}/leads/attach-lead-list", data=body)

    async def stop_future_emails(self, campaign_id: int, lead_ids: List[int]) -> Dict:
        return await self.make_request("POST", f"/api/campaigns/{campaign_id}/leads/stop-future-emails", data={"lead_ids": lead_ids})

    # ---------- Events stats ----------
    async def campaign_events_stats(self, start_date: str, end_date: str,
                                    sender_email_ids: Optional[List[int]]=None,
                                    campaign_ids: Optional[List[int]]=None) -> Dict:
        params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
        if sender_email_ids:
            for i, sid in enumerate(sender_email_ids):
                params[f"sender_email_ids[{i}]"] = sid
        if campaign_ids:
            for i, cid in enumerate(campaign_ids):
                params[f"campaign_ids[{i}]"] = cid
        return await self.make_request("GET", "/api/campaign-events/stats", params=params)

    # ---------- Email accounts + warmup ----------
    async def list_email_accounts(self, **filters) -> Dict:
        params: Dict[str, Any] = {}
        for k, v in (filters or {}).items():
            if isinstance(v, list):
                for i, val in enumerate(v): params[f"{k}[{i}]"] = val
            else:
                params[k] = v
        return await self.make_request("GET", "/api/sender-emails", params=params)

    async def list_warmup_accounts(self, **filters) -> Dict:
        params: Dict[str, Any] = {}
        for k, v in (filters or {}).items():
            if isinstance(v, list):
                for i, val in enumerate(v): params[f"{k}[{i}]"] = val
            else:
                params[k] = v
        return await self.make_request("GET", "/api/warmup/sender-emails", params=params)

    async def get_warmup_account(self, sender_email_id: int, start_date: Optional[str]=None, end_date: Optional[str]=None) -> Dict:
        params = {}
        if start_date: params["start_date"] = start_date
        if end_date:   params["end_date"] = end_date
        return await self.make_request("GET", f"/api/warmup/sender-emails/{sender_email_id}", params=params)

    async def warmup_enable(self, sender_email_ids: List[int]) -> Dict:
        return await self.make_request("PATCH", "/api/warmup/sender-emails/enable", data={"sender_email_ids": sender_email_ids})
    async def warmup_disable(self, sender_email_ids: List[int]) -> Dict:
        return await self.make_request("PATCH", "/api/warmup/sender-emails/disable", data={"sender_email_ids": sender_email_ids})
    async def warmup_update_limits(self, sender_email_ids: List[int], daily_limit: int, daily_reply_limit: Optional[int]=None) -> Dict:
        data: Dict[str, Any] = {"sender_email_ids": sender_email_ids, "daily_limit": daily_limit}
        if daily_reply_limit is not None: data["daily_reply_limit"]=daily_reply_limit
        return await self.make_request("PATCH", "/api/warmup/sender-emails/update-daily-warmup-limits", data=data)

    async def aclose(self):
        try: await self._client.aclose()
        except Exception: pass

# -------------------- Tools ---------------------
client: Optional[EmailBisonClient] = None

@server.list_tools()
async def list_tools() -> List[types.Tool]:
    return [
        types.Tool(name="list_campaigns", description="List campaigns", inputSchema={
            "type":"object","properties":{"status":{"type":"string"},"tag_ids":{"type":"array","items":{"type":"integer"}}}
        }),
        types.Tool(name="analyze_campaign", description="Campaign overview + stats + replies", inputSchema={
            "type":"object","properties":{
                "campaign_id":{"type":"integer"},
                "start_date":{"type":"string"},"end_date":{"type":"string"},
                "include_replies":{"type":"boolean","default":True},
                "include_sequence":{"type":"boolean","default":True}},
            "required":["campaign_id"]
        }),
        types.Tool(name="analyze_replies", description="Analyze replies for a campaign", inputSchema={
            "type":"object","properties":{
                "campaign_id":{"type":"integer"},
                "status_filter":{"type":"string","enum":["interested","automated_reply","not_automated_reply"]},
                "folder":{"type":"string"},"analyze_threads":{"type":"boolean","default":False}},
            "required":["campaign_id"]
        }),
        types.Tool(name="campaign_performance_summary", description="Compare performance", inputSchema={
            "type":"object","properties":{"campaign_ids":{"type":"array","items":{"type":"integer"}},"start_date":{"type":"string"},"end_date":{"type":"string"}}}),
        types.Tool(name="lead_engagement_analysis", description="Lead engagement tiers", inputSchema={
            "type":"object","properties":{"campaign_id":{"type":"integer"},"engagement_threshold":{"type":"integer","default":2}},"required":["campaign_id"]}),
        types.Tool(name="sequence_optimization_insights", description="Sequence step insights", inputSchema={
            "type":"object","properties":{"campaign_id":{"type":"integer"}},"required":["campaign_id"]}),
        types.Tool(name="dump_replies_json", description="Raw replies JSON (debug)", inputSchema={
            "type":"object","properties":{"campaign_id":{"type":"integer"},"status_filter":{"type":"string"},"folder":{"type":"string"}},"required":["campaign_id"]}),
        # ----- NEW per docs -----
        types.Tool(name="create_campaign", description="Create a campaign (POST /api/campaigns)", inputSchema={
            "type":"object","properties":{"name":{"type":"string"},"type":{"type":"string","default":"outbound"},"extra":{"type":"object"}},"required":["name"]}),
        types.Tool(name="add_leads_to_campaign", description="Attach leads or a lead list to a campaign", inputSchema={
            "type":"object","properties":{
                "campaign_id":{"type":"integer"},
                "lead_ids":{"type":"array","items":{"type":"integer"}},
                "lead_list_id":{"type":"integer"},
                "allow_parallel_sending":{"type":"boolean","default":False}},
            "oneOf":[{"required":["campaign_id","lead_ids"]},{"required":["campaign_id","lead_list_id"]}]
        }),
        types.Tool(name="stop_future_emails", description="Stop future emails for specific leads in a campaign", inputSchema={
            "type":"object","properties":{"campaign_id":{"type":"integer"},"lead_ids":{"type":"array","items":{"type":"integer"}}},"required":["campaign_id","lead_ids"]}),
        types.Tool(name="campaign_events_stats", description="Daily event stats (GET /api/campaign-events/stats)", inputSchema={
            "type":"object","properties":{
                "start_date":{"type":"string"},"end_date":{"type":"string"},
                "sender_email_ids":{"type":"array","items":{"type":"integer"}},
                "campaign_ids":{"type":"array","items":{"type":"integer"}}},
            "required":["start_date","end_date"]
        }),
        types.Tool(name="list_email_accounts", description="List sender emails", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="list_warmup_accounts", description="List sender emails with warmup info", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="warmup_account_details", description="Warmup details for a sender email", inputSchema={
            "type":"object","properties":{"sender_email_id":{"type":"integer"},"start_date":{"type":"string"},"end_date":{"type":"string"}},"required":["sender_email_id"]}),
        types.Tool(name="warmup_enable", description="Enable warmup for sender emails", inputSchema={
            "type":"object","properties":{"sender_email_ids":{"type":"array","items":{"type":"integer"}}},"required":["sender_email_ids"]}),
        types.Tool(name="warmup_disable", description="Disable warmup for sender emails", inputSchema={
            "type":"object","properties":{"sender_email_ids":{"type":"array","items":{"type":"integer"}}},"required":["sender_email_ids"]}),
        types.Tool(name="warmup_update_limits", description="Update daily warmup limits", inputSchema={
            "type":"object","properties":{"sender_email_ids":{"type":"array","items":{"type":"integer"}},"daily_limit":{"type":"integer"},"daily_reply_limit":{"type":"integer"}},"required":["sender_email_ids","daily_limit"]}),
        types.Tool(name="raw_request", description="Send a raw HTTP request to the API (debug)", inputSchema={
            "type":"object","properties":{
                "method":{"type":"string","enum":["GET","POST","PATCH","PUT","DELETE","HEAD","OPTIONS"]},
                "path":{"type":"string"},"params":{"type":"object"},"body":{"type":"object"}},
            "required":["method","path"]
        }),
    ]

@server.call_tool()
async def call_tool(name: str, args: Dict[str, Any]) -> List[types.TextContent]:
    if not client:
        return [types.TextContent(type="text", text="Error: client not initialized. Set EMAILBISON_API_KEY.")]

    try:
        if name == "list_campaigns":
            res = await client.get_campaigns(status=args.get("status"), tag_ids=args.get("tag_ids"))
            out="# Campaigns\n\n"
            for c in res.get("data", []):
                out+=f"## {c.get('name')} (ID {c.get('id')})\n- Status: {c.get('status')}\n- Emails Sent: {c.get('emails_sent')}\n- Opens: {c.get('opened')} (U: {c.get('unique_opens')})\n- Replies: {c.get('replied')} (U: {c.get('unique_replies')})\n- Bounced: {c.get('bounced')}\n- Interested: {c.get('interested')}\n- Total Leads: {c.get('total_leads')}\n\n"
            return [types.TextContent(type="text", text=out)]

        elif name == "analyze_campaign":
            cid = int(args["campaign_id"])
            camp = await client.get_campaign_details(cid); c = camp.get("data", {})
            stats = await client.get_campaign_stats(cid, args.get("start_date"), args.get("end_date")); s = stats.get("data", {})
            out = f"# Campaign: {c.get('name')}\n\n## Overview\n- Status: {c.get('status')}\n- Type: {c.get('type')}\n- Created: {c.get('created_at')}\n\n## Metrics\n- Emails Sent: {s.get('emails_sent',0)}\n- Leads Contacted: {s.get('total_leads_contacted',0)}\n- Open %: {s.get('opened_percentage',0)}\n- Reply %: {s.get('unique_replies_per_contact_percentage',0)}\n- Bounce %: {s.get('bounced_percentage',0)}\n- Interested %: {s.get('interested_percentage',0)}\n"
            if args.get("include_sequence", True):
                try:
                    seq = await client.get_sequence_steps(cid)
                    if (seq.get("data", {}) or {}).get("sequence_steps"):
                        out += "\n## Sequence Step Performance\n"
                        for st in s.get("sequence_step_stats", []):
                            out += f"- Step {st.get('sequence_step_id')}: sent {st.get('sent',0)}, u-opens {st.get('unique_opens',0)}, u-replies {st.get('unique_replies',0)}, interested {st.get('interested',0)}\n"
                except Exception as e: log_debug(f"sequence skip: {e!r}")
            if args.get("include_replies", True):
                try:
                    reps = await client.get_campaign_replies(cid); data = reps.get("data", [])
                    if data:
                        out += f"\n## Replies ({len(data)})\n- Interested: {sum(1 for r in data if r.get('interested'))}\n- Automated: {sum(1 for r in data if r.get('automated_reply'))}\n"
                        out += "\n### Samples\n"
                        for r in data[:5]:
                            body=(r.get('text_body') or "")[:200].replace("\n"," ").strip()
                            out+=f"- {r.get('from_name','?')} <{r.get('from_email_address')}> — {r.get('subject')} — {body}...\n"
                except Exception as e: log_debug(f"replies skip: {e!r}")
            return [types.TextContent(type="text", text=out)]

        elif name == "analyze_replies":
            cid = int(args["campaign_id"])
            res = await client.get_campaign_replies(cid, status=args.get("status_filter"), folder=args.get("folder"))
            rd = res.get("data", []) or []
            interested=[r for r in rd if r.get("interested")]; automated=[r for r in rd if r.get("automated_reply")]
            out = f"# Replies for {cid}\n- Total: {len(rd)}\n- Interested: {len(interested)}\n- Automated: {len(automated)}\n\n"
            for i, r in enumerate([x for x in rd if not x.get("automated_reply")][:20], 1):
                prev=(r.get("text_body") or "")[:300].replace("\n"," ").strip()
                out+=f"### #{i} {r.get('from_email_address')} ({r.get('from_name','')})\nSubject: {r.get('subject')}\nInterested: {bool(r.get('interested'))}\nMsg: {prev}{'...' if len(prev)==300 else ''}\n\n"
            return [types.TextContent(type="text", text=out)]

        elif name == "campaign_performance_summary":
            ids = args.get("campaign_ids") or [c.get("id") for c in (await client.get_campaigns()).get("data", [])][:10]
            perf=[]
            for cid in ids:
                try:
                    c = await client.get_campaign_details(int(cid))
                    s = await client.get_campaign_stats(int(cid), args.get("start_date"), args.get("end_date"))
                    cd, sd = c.get("data", {}), s.get("data", {})
                    perf.append({"name":cd.get("name"),"id":int(cid),"status":cd.get("status"),
                                 "emails":int(sd.get("emails_sent",0) or 0),
                                 "open":float(sd.get("opened_percentage",0) or 0.0),
                                 "reply":float(sd.get("unique_replies_per_contact_percentage",0) or 0.0),
                                 "int":float(sd.get("interested_percentage",0) or 0.0)})
                except Exception as e: log_debug(f"skip {cid}: {e!r}")
            perf.sort(key=lambda x: x["reply"], reverse=True)
            out="# Performance (by Reply %)\n\n"
            for i, p in enumerate(perf[:5], 1):
                out+=f"{i}. {p['name']} (ID {p['id']}) — Sent {p['emails']}, Open {p['open']}%, Reply {p['reply']}%, Interested {p['int']}%\n"
            return [types.TextContent(type="text", text=out)]

        elif name == "lead_engagement_analysis":
            cid=int(args["campaign_id"]); thr=int(args.get("engagement_threshold",2))
            leads = await client.get_campaign_leads(cid); ld = leads.get("data", []) or []
            hi,eng,low,none = [],[],[],[]
            for L in ld:
                st = L.get("lead_campaign_data", {}) or {}
                opens, replies = int(st.get("opens",0) or 0), int(st.get("replies",0) or 0)
                score = opens + replies*3
                bucket = hi if score>=thr*3 else eng if score>=thr else low if score>0 else none
                bucket.append((score,L))
            out=f"# Lead Engagement (Campaign {cid})\nTotal leads: {len(ld)}\n"
            out+=f"- Highly: {len(hi)} | Engaged: {len(eng)} | Low: {len(low)} | None: {len(none)}\n\n"
            if hi:
                out+="## Top Engaged\n"
                for score,L in sorted(hi, key=lambda x: x[0], reverse=True)[:10]:
                    out+=f"- {L.get('first_name','')} {L.get('last_name','')} <{L.get('email')}> — score {score}\n"
            return [types.TextContent(type="text", text=out)]

        elif name == "sequence_optimization_insights":
            cid=int(args["campaign_id"]); stats=await client.get_campaign_stats(cid); seq=await client.get_sequence_steps(cid)
            sd, steps = stats.get("data", {}) or {}, (seq.get("data", {}) or {}).get("sequence_steps") or []
            sstats = sd.get("sequence_step_stats", []) or []
            out="# Sequence Insights\n"
            if steps:
                out+=f"- Steps: {len(steps)} | Variants: {'Yes' if any(s.get('variant') for s in steps) else 'No'}\n"
                for i, st in enumerate(steps, 1):
                    ss = next((x for x in sstats if x.get("sequence_step_id")==st.get("id")), {})
                    sent = ss.get("sent",0) or 0; rep = ss.get("unique_replies",0) or 0
                    rate = (rep/max(sent,1))*100
                    out+=f"\n{i}) {st.get('email_subject','(no subject)')} — wait {st.get('wait_in_days',0)}d, thread:{bool(st.get('thread_reply'))}, var:{bool(st.get('variant'))}\n   sent {sent}, reply% {rate:.1f}, interested {ss.get('interested',0) or 0}\n"
            return [types.TextContent(type="text", text=out)]

        elif name == "dump_replies_json":
            cid=int(args["campaign_id"])
            res = await client.get_campaign_replies(cid, status=args.get("status_filter"), folder=args.get("folder"))
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)[:50000]}\n```")]

        # ----- NEW per docs -----
        elif name == "create_campaign":
            extra = args.get("extra") or {}
            res = await client.create_campaign(args["name"], args.get("type","outbound"), **extra)
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)}\n```")]

        elif name == "add_leads_to_campaign":
            cid = int(args["campaign_id"]); aps = bool(args.get("allow_parallel_sending", False))
            if "lead_list_id" in args:
                res = await client.attach_lead_list(cid, int(args["lead_list_id"]), aps)
            else:
                res = await client.attach_leads(cid, [int(x) for x in args["lead_ids"]], aps)
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)}\n```")]

        elif name == "stop_future_emails":
            res = await client.stop_future_emails(int(args["campaign_id"]), [int(x) for x in args["lead_ids"]])
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)}\n```")]

        elif name == "campaign_events_stats":
            res = await client.campaign_events_stats(
                args["start_date"], args["end_date"],
                args.get("sender_email_ids"), args.get("campaign_ids")
            )
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)[:50000]}\n```")]

        elif name == "list_email_accounts":
            res = await client.list_email_accounts()
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)[:50000]}\n```")]

        elif name == "list_warmup_accounts":
            res = await client.list_warmup_accounts()
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)[:50000]}\n```")]

        elif name == "warmup_account_details":
            res = await client.get_warmup_account(int(args["sender_email_id"]), args.get("start_date"), args.get("end_date"))
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)[:50000]}\n```")]

        elif name == "warmup_enable":
            res = await client.warmup_enable([int(x) for x in args["sender_email_ids"]])
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)}\n```")]

        elif name == "warmup_disable":
            res = await client.warmup_disable([int(x) for x in args["sender_email_ids"]])
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)}\n```")]

        elif name == "warmup_update_limits":
            res = await client.warmup_update_limits([int(x) for x in args["sender_email_ids"]],
                                                    int(args["daily_limit"]),
                                                    int(args["daily_reply_limit"]) if args.get("daily_reply_limit") is not None else None)
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)}\n```")]

        elif name == "raw_request":
            method = args["method"].upper(); path = args["path"]
            res = await client.make_request(method, path, params=args.get("params"), data=args.get("body"))
            return [types.TextContent(type="text", text=f"```json\n{json.dumps(res,indent=2)[:50000]}\n```")]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        last = getattr(client, "last_http", {}) or {}
        details = json.dumps({
            "error": str(e),
            "last_http": {
                "method": last.get("method"), "url": last.get("url"), "status": last.get("status"),
                "content_type": last.get("content_type"), "request_params": last.get("request_params"),
                "request_json": last.get("request_json"), "response_preview": last.get("response_preview"),
            }
        }, indent=2)
        return [types.TextContent(type="text", text=f"Tool error:\n```json\n{details}\n```")]

# -------------------- Capabilities shim --------------------
def _capabilities():
    """
    Compatibility shim for different MCP versions.
    Newer MCP requires 'experimental_capabilities', older may not.
    """
    try:
        # Most recent signature (keyword args)
        return server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        )
    except TypeError:
        # Try positional variants for older releases
        try:
            return server.get_capabilities(NotificationOptions(), {})
        except TypeError:
            return server.get_capabilities(NotificationOptions())

# -------------------- Main ----------------------
async def main():
    try:
        log_error("Starting Email Bison MCP Server…")
        api_key = os.getenv("EMAILBISON_API_KEY")
        red = f"{api_key[:10]}...{api_key[-6:]}" if api_key else "None"
        log_error(f"API Key: {red}")
        if api_key:
            global client
            client = EmailBisonClient(api_key, base_url=os.getenv("EMAILBISON_BASE_URL"))
            log_error("Client initialized")
        else:
            log_error("WARNING: EMAILBISON_API_KEY is not set")
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="email-bison",
                    server_version="0.3.0",
                    capabilities=_capabilities(),  # <-- version-safe
                ),
            )
    except Exception as e:
        log_error(f"Fatal in main(): {e}")
        import traceback; log_error(traceback.format_exc()); raise
    finally:
        if client: await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
