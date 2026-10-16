# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BadgeCade (neotechspurts)
# Patches shopdeck (https://github.com/Aftendo/shopdeck, GPL-2.0).
"""Changes applied to shopdeck when the container is built."""
from pathlib import Path


def patch(path, old, new):
    p = Path(path)
    s = p.read_text()
    assert s.count(old) == 1, f"{path} changed upstream, patch needs updating"
    p.write_text(s.replace(old, new))


# Badge Arcade plays get used up, so buying them again has to make a new
# purchase. Shopdeck handed back the first ticket every time and numbered
# every purchase 1.
patch("api/views.py", """   try:
      owned = ownedTicket.objects.get(item=aitem, owner=ds)
   except ObjectDoesNotExist:
      ds.balance = ds.balance - aitem.price
      ds.save()
      owned = ownedTicket.objects.create(item=aitem, ticketid=(b'\\x00\\x04'+ os.urandom(6)).hex(), owner=ds)
      owned.save()
   res = {"transaction_results": {"transaction_result":[{"transaction_id":1,""", """   # new ticket every time, plays are consumable
   ds.balance = ds.balance - aitem.price
   ds.save()
   owned = ownedTicket.objects.create(item=aitem, ticketid=(b'\\x00\\x04'+ os.urandom(6)).hex(), owner=ds)
   res = {"transaction_results": {"transaction_result":[{"transaction_id":owned.pk,""")

# A console that used another shopdeck server already has an account id
# saved. Reuse it for the new account so the console doesn't see it change.
patch("ecs.py", """            ds = Client3DS.objects.create(consoleid=""", """            prev = parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:GetAccountStatus'].get('ecs:AccountId')
            keep = {"id": int(prev)} if prev and str(prev).isdigit() and not Client3DS.objects.filter(id=int(prev)).exists() else {}
            ds = Client3DS.objects.create(**keep, consoleid=""")

# US consoles need a tax address before buying. They read my/tax_location,
# look the ZIP code up in <country>/tax_locations, then save the choice with
# my/tax_location/!put. Shopdeck had only the first (a placeholder), so the
# lookup and the save 404ed (026-2404). Plays are free, so the address is
# only shown to the player: the state comes from the ZIP code's first three
# digits, and each console's saved ZIP is kept in /data/tax_locations.json.
patch("api/urls.py", """    path('my/tax_location', views.tax_location, name="taxloc"),
""", """    path('my/tax_location', views.tax_location, name="taxloc"),
    path('my/tax_location/!put', views.tax_location_put, name="taxlocput"),
    path('<str:country>/tax_locations', views.tax_locations, name="taxlocs"),
""")
patch("api/views.py", """   res = {"tax_location": {"state": "United States", "state_code": ds.country, "id": 71647}}
   return JsonResponse(res)""", """   saved = _saved_postal_codes().get(str(ds.consoleid))
   if saved:
      return JsonResponse({"tax_location": _tax_location(saved)})
   res = {"tax_location": {"state": "United States", "state_code": ds.country, "id": 71647}}
   return JsonResponse(res)""")
Path("api/views.py").write_text(Path("api/views.py").read_text() + '''

# --- badgecade: US tax address ---
import builtins as _builtins
import json as _json
import threading as _threading

_TAX_FILE = "/data/tax_locations.json"
_TAX_LOCK = _threading.Lock()
_TAX_ID_BASE = 1000000  # tax_location id = base + ZIP code
_ZIP3_STATES = (
   (5, 5, "NY"), (6, 9, "PR"), (10, 27, "MA"), (28, 29, "RI"), (30, 38, "NH"),
   (39, 49, "ME"), (50, 54, "VT"), (55, 55, "MA"), (56, 59, "VT"), (60, 69, "CT"),
   (70, 89, "NJ"), (90, 99, "AE"), (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"),
   (200, 200, "DC"), (201, 201, "VA"), (202, 205, "DC"), (206, 219, "MD"), (220, 246, "VA"),
   (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"), (300, 319, "GA"), (320, 339, "FL"),
   (340, 340, "AA"), (341, 349, "FL"), (350, 369, "AL"), (370, 385, "TN"), (386, 397, "MS"),
   (398, 399, "GA"), (400, 427, "KY"), (430, 459, "OH"), (460, 479, "IN"), (480, 499, "MI"),
   (500, 528, "IA"), (530, 549, "WI"), (550, 567, "MN"), (570, 577, "SD"), (580, 588, "ND"),
   (590, 599, "MT"), (600, 629, "IL"), (630, 658, "MO"), (660, 679, "KS"), (680, 693, "NE"),
   (700, 715, "LA"), (716, 729, "AR"), (730, 732, "OK"), (733, 733, "TX"), (734, 749, "OK"),
   (750, 799, "TX"), (800, 816, "CO"), (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"),
   (850, 865, "AZ"), (870, 884, "NM"), (885, 885, "TX"), (889, 898, "NV"), (900, 961, "CA"),
   (962, 966, "AP"), (967, 968, "HI"), (969, 969, "GU"), (970, 979, "OR"), (980, 994, "WA"),
   (995, 999, "AK"),
)


def _state_for_zip(postal_code):
   prefix = int(postal_code[:3])
   for low, high, state in _ZIP3_STATES:
      if low <= prefix <= high:
         return state
   return "US"


def _tax_location(postal_code):
   state = _state_for_zip(postal_code)
   return {"id": _TAX_ID_BASE + int(postal_code), "state": state, "state_code": state,
           "county": "", "city": "", "postal_code": postal_code}


def _saved_postal_codes():
   try:
      with _builtins.open(_TAX_FILE) as f:
         return _json.load(f)
   except (OSError, ValueError):
      return {}


@csrf_exempt
def tax_locations(request, country):
   postal_code = request.GET.get("postal_code", "")
   if not (postal_code.isdigit() and len(postal_code) == 5):
      # Canada and other non-US consoles ask by province/state, not ZIP code
      state = request.GET.get("state", "")
      if country != "US" and state:
         return JsonResponse({"tax_locations": {"tax_location": [{"id": 71647, "state": state, "state_code": state,
                                                                    "county": "", "city": "", "postal_code": ""}]}})
      return JsonResponse({"error": {"code": "2404", "message": "Please enter a valid ZIP code."}}, status=400)
   return JsonResponse({"tax_locations": {"tax_location": [_tax_location(postal_code)]}})


@csrf_exempt
def tax_location_put(request):
   try:
      ds = Client3DS.objects.get(consoleid=request.session["deviceid"])
   except:
      return JsonResponse({"error": {"code": "3010","message": "The connection to the server has\\ntimed out due to user inactivity.\\n\\nPlease restart Nintendo eShop\\nand try again."}}, status=400)
   try:
      postal_code = "%05d" % (int(request.POST.get("tax_location_id", "")) - _TAX_ID_BASE)
   except ValueError:
      postal_code = ""
   if postal_code.isdigit() and len(postal_code) == 5:
      with _TAX_LOCK:
         saved = _saved_postal_codes()
         saved[str(ds.consoleid)] = postal_code
         with _builtins.open(_TAX_FILE + ".tmp", "w") as f:
            _json.dump(saved, f)
         os.replace(_TAX_FILE + ".tmp", _TAX_FILE)
   return JsonResponse({})
''')

# Shopdeck writes the account id into the ticket by reading its decimal
# digits as hex, which only fits 4 bytes for ids of up to 8 digits. Consoles
# that keep their real eShop account id (9+ digits, e.g. US consoles) crashed
# AccountGetETickets with OverflowError (005-4800). Fall back to the plain
# 32-bit id, the way a real ticket stores it; short ids are unchanged.
patch("ecs.py", """            tk.write(int.to_bytes(int(aid, base=16), 4, "big"))""", """            aid_value = int(aid, base=16)
            if aid_value > 0xFFFFFFFF:
                aid_value = ds.id & 0xFFFFFFFF
            tk.write(int.to_bytes(aid_value, 4, "big"))""")

# Plays show a price in Credits but stay free: Nintendo's four play bundles
# (5, 10, 15, 20 plays; tools/play_bundles.py) cost 1-4 credits, every
# console has a balance of 4 credits, the purchase never deducts it, and
# amounts use a US style "1.00 Credits" in all regions (shopdeck printed
# "0,00 Credit"). The 3DS refuses a purchase that costs more than the
# balance, so the balance has to be at least the dearest bundle.
def replace_all(path, old, new):
    p = Path(path)
    s = p.read_text()
    assert old in s, f"{path}: {old!r} not found, patch needs updating"
    p.write_text(s.replace(old, new))


patch("api/views.py", """   ds.balance = ds.balance - aitem.price
   ds.save()
   owned = ownedTicket""", """   # the price is only shown; plays never take the balance
   owned = ownedTicket""")
patch("ecs.py", "is_terminated=False, balance=0,", "is_terminated=False, balance=4,")
replace_all("api/views.py", ',00 Credit"', '.00 Credits"')
replace_all("api/views.py", '+" Credit"', '+".00 Credits"')
replace_all("api/views.py", '_suffix":" Credit"', '_suffix":" Credits"')
replace_all("api/views.py", '"# ### ### ###,##"', '"#,###,###,###.##"')

# the web portal and the game download CDN aren't copied in
patch("main.py", "import ecs, ias, cas, cdn, assetcdn\n", "import ecs, ias, cas\n")
patch("main.py", "app.register_blueprint(cdn.ccs)\napp.register_blueprint(assetcdn.cdn)\n", "")
patch("shopdeck/urls.py", "    path('', include('webui.urls')),\n", "")
# without the portal, logged-out visitors were sent to a home page that no
# longer exists, which locked everyone out of the admin page
patch("shopdeckdb/middleware.py", 'and not request.path.startswith("/login")', 'and not request.path.startswith("/admin") and not request.path.startswith("/static") and not request.path.startswith("/login")')
patch("shopdeck/urls.py", "handler404 = 'webui.views.err404'\nhandler500 = 'webui.views.err500'", "")

# our settings
Path("shopdeck/settings.py").write_text(Path("shopdeck/settings.py").read_text() + '''
# --- badgecade ---
import os
SECRET_KEY = os.environ["SHOPDECK_SECRET_KEY"]
DEBUG = os.environ.get("SHOPDECK_DEBUG", "0") == "1"
DATABASES["default"]["NAME"] = "/data/db.sqlite3"
SOAP_URL = os.environ.get("SHOPDECK_SOAP_URL", "ecs.c.shop.nintendowifi.net")
METADATA_API_URL = os.environ.get("SHOPDECK_METADATA_URL", "samurai.ctr.shop.nintendo.net")
TEMPLATES[0]["DIRS"] = []
STATICFILES_DIRS = []
STATIC_ROOT = "/app/staticfiles"
''')
print("shopdeck patched")

# The HOME Menu Theme Shop lists ten theme packs at once (DLC titles
# 0004008C00008F00..09). Shopdeck only handled one title id and answered
# "Error" (console error 005-4034). Answer with the packs we know (none yet).
patch("cas.py", """        try:
            title = Title.objects.get(tid=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListTitlesEx']['cas:TitleId'])
        except ObjectDoesNotExist:
            return "Error"
        r = make_response(render_template("cas/listTitlesEx.xml", id=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListTitlesEx']['cas:DeviceId'], message=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListTitlesEx']['cas:MessageId'],time=int(round(time.time()*1000)), t=title))""", """        req = parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListTitlesEx']
        tids = req['cas:TitleId'] if isinstance(req['cas:TitleId'], list) else [req['cas:TitleId']]
        titles = [t for t in (Title.objects.filter(tid=tid).first() for tid in tids) if t is not None]
        # titles marked not public (test packs) only for the consoles in /cdn/.test_devices
        try:
            test_devices = open("/cdn/.test_devices").read().split()
        except OSError:
            test_devices = []
        titles = [t for t in titles if t.public or str(req['cas:DeviceId']) in test_devices]
        # a theme pack's own item only; its themes' items are listed by ListContentSetsEx
        import json
        for t in titles:
            try:
                theme_items = {s["item_id"] for s in json.load(open("/cdn/%s/contentsets.json" % t.tid.upper()))}
            except (OSError, ValueError):
                theme_items = set()
            t.pack_items = [i for i in t.item_set.all() if i.id not in theme_items
                            # nor deleted themes' items (R08000003): a pack with many listed
                            # its 100+ old items, the answer got so big the console only took
                            # in the first pack (All Themes showed one pack of four)
                            and not i.itemcode.startswith("R") and not i.itemcode.isdigit()]
        r = make_response(render_template("cas/listTitlesEx.xml", id=req['cas:DeviceId'], message=req['cas:MessageId'], time=int(round(time.time()*1000)), titles=titles))""")
Path("templates/cas/listTitlesEx.xml").write_text("""{% extends 'header.xml' %}{% block main %}<ListTitlesExResponse xmlns="urn:cas.wsapi.broadon.com"><Version>2.0</Version><DeviceId>{{ id }}</DeviceId><MessageId>{{ message }}</MessageId><TimeStamp>{{ time }}</TimeStamp><ErrorCode>0</ErrorCode><ListResultTotalSize>{{ titles|length }}</ListResultTotalSize>{% for t in titles %}<Titles><TitleId>{{ t.tid }}</TitleId><Attributes><Name>MaxUserFileSize</Name><Value>{{ t.size }}</Value></Attributes><Attributes><Name>Version</Name><Value>{{ t.version }}</Value></Attributes>{% for i in t.pack_items %}<Prices><ItemId>{{ i.id }}</ItemId><Price><Amount>{{ i.price }}</Amount><Currency>CREDIT</Currency></Price><Limits><Limits>{{ i.limit }}</Limits><LimitKind>PR</LimitKind></Limits><LicenseKind>PERMANENT</LicenseKind></Prices>{% endfor %}</Titles>{% endfor %}</ListTitlesExResponse>{% endblock %}""")

# The Theme Shop "buys" a theme pack's free part (DLC content 0, the pack's
# theme list) through aocs/!purchase_ctr before it lists any themes. Same as a
# ticket purchase, but a pack is owned once, so the existing ticket is reused.
patch("api/urls.py", """    path('<str:country>/title/<int:tid>/tickets/!purchase_ctr', views.purcahse_ticket, name="purchasetik"),""",
"""    path('<str:country>/title/<int:tid>/tickets/!purchase_ctr', views.purcahse_ticket, name="purchasetik"),
    path('<str:country>/title/<str:tid>/aocs/!purchase_ctr', views.purchase_aoc, name="purchaseaoc"),""")
Path("api/views.py").write_text(Path("api/views.py").read_text() + '''

def pack_ticketid(ds, aitem):
   """One ticket per console and theme pack under one id that never changes, as
   Nintendo's: a purchase (or buying a theme again, or a theme given) answers
   with that id, the console fetches the ticket again and its copy is replaced
   with rights for every theme it owns there, so a new theme shows at once.
   A new id per purchase had left consoles with several tickets for a pack,
   and Change Theme went by an old one (themes bought later didn't show,
   2026-10-13; fixed on the console by deleting the pack's tickets in FBI).
   Such consoles get their tickets for the pack merged into the oldest id
   here; the ticket list then names it alone and the console deletes the
   others at its next ticket sync."""
   if str(aitem.title.tid).upper().startswith("0004008C"):
      rows = ownedTicket.objects.filter(owner=ds, item__title=aitem.title)
      first = rows.order_by("id").first()
      if first is not None:
         rows.exclude(ticketid=first.ticketid).update(ticketid=first.ticketid)
         return first.ticketid
   return (b'\\x00\\x04'+ os.urandom(6)).hex()


@csrf_exempt
def purchase_aoc(request, country, tid):
   try:
      aitem = item.objects.get(id=int(request.POST.get("item_id[]")))
   except Exception:
      return JsonResponse({"error": {"code": "2404", "message": "Item not found."}}, status=404)
   # the Theme Shop has no eShop session; the proxy passes on the device id
   device = request.session.get("deviceid") or request.headers.get("X-Badgecade-Device-Id")
   ds = Client3DS.objects.filter(consoleid=str(device)).first() if device else None
   if ds is None:
      return JsonResponse({"error": {"code": "3010","message": "The connection to the server has\\ntimed out due to user inactivity.\\n\\nPlease restart Nintendo eShop\\nand try again."}}, status=400)
   owned = ownedTicket.objects.filter(item=aitem, owner=ds).first()
   if owned is None:
      owned = ownedTicket.objects.create(item=aitem, ticketid=(b'\\x00\\x04'+ os.urandom(6)).hex(), owner=ds)
   # the pack's one ticket (also when the theme was already bought: buying
   # it again fetches the ticket with every owned theme)
   ticketid = pack_ticketid(ds, aitem) if str(aitem.title.tid).upper().startswith("0004008C") else owned.ticketid
   res = {"transaction_results": {"transaction_result":[{"transaction_id":owned.pk,"title_id":aitem.title.tid,"ticket_id":int(ticketid, base=16),"post_balance":{"amount":str(ds.balance)+".00 Credits","currency":"CREDIT","raw_value":str(ds.balance)},"integrated_account":True}]}}
   return JsonResponse(res)
''')

# Theme packs (DLC 0004008C...) need a ticket that owns their contents, like
# a title ticket (basetik.bin grants contents 0-255), not the plays licence.
# The console may ask again for a pack's ticket, so it's kept, not deleted.
patch("ecs.py", """        if istitle:
            with open("basetik.bin", "rb") as f:""", """        is_dlc = istik and owned.item.title.tid.upper().startswith("0004008C")
        if istitle or is_dlc:
            with open("basetik.bin", "rb") as f:""")
patch("ecs.py", """        if istik:
            owned.delete()""", """        if istik and not is_dlc:
            owned.delete()""")

# The Theme Shop asks for the size of each pack content it's about to
# download. Answer from the pack files on the CDN (cdn/<title id>/).
patch("cas.py", """    if "cas:ListItems" in parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']:""", """    if "cas:GetContentSizes" in parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']:
        req = parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:GetContentSizes']
        indexes = req.get('cas:ContentIndex', [])
        # each ContentIndex element may hold several indexes ("0,1,2")
        indexes = [i for part in (indexes if isinstance(indexes, list) else [indexes]) for i in str(part).split(",") if i.strip()]
        sizes = []
        for index in indexes:
            path = "/cdn/%s/%08X.app" % (str(req['cas:TitleId']).upper(), int(index))
            sizes.append(os.path.getsize(path) if os.path.isfile(path) else 0)
        # Answer shape switch for testing: /cdn/.getcontentsizes (default:
        # Nintendo's format, below).
        try:
            shape = open("/cdn/.getcontentsizes").read().strip()
        except OSError:
            shape = "ContentSize"
        pairs = list(zip([int(i) for i in indexes], sizes))
        if shape == "error":  # diagnostics: a deliberate CAS error
            r = make_response(render_template("cas/getContentSizes.xml", id=req['cas:DeviceId'], message=req['cas:MessageId'], time=int(round(time.time()*1000)), body="").replace("<ErrorCode>0</ErrorCode>", "<ErrorCode>1</ErrorCode><ErrorMessage>BadgeCade test</ErrorMessage>"))
            r.headers.set("Content-Type", "text/xml; charset=utf-8")
            return r
        if shape == "wide":  # many possible element names at once
            body = "".join("<ContentSize>%d</ContentSize><Size>%d</Size><Sizes>%d</Sizes>" % (size, size, size) for _, size in pairs)
            body += "<TotalSize>%d</TotalSize><ContentsSize>%d</ContentsSize>" % (sum(sizes), sum(sizes))
            body += "".join("<ContentSizeInfo><ContentIndex>%d</ContentIndex><Size>%d</Size></ContentSizeInfo>" % p for p in pairs)
            body += "".join("<ContentInfo><Index>%d</Index><Size>%d</Size></ContentInfo>" % p for p in pairs)
        elif shape == "Contents":
            body = "".join("<Contents><ContentIndex>%d</ContentIndex><ContentSize>%d</ContentSize></Contents>" % p for p in pairs)
        elif shape == "ContentSizesNested":
            body = "".join("<ContentSizes><ContentIndex>%d</ContentIndex><ContentSize>%d</ContentSize></ContentSizes>" % p for p in pairs)
        elif shape == "ContentSizes":
            body = "".join("<ContentSizes>%d</ContentSizes>" % size for _, size in pairs)
        else:
            # Nintendo's answer (as parsed by luigoalma/cleaninty's CAS client):
            # one ContentSize per index as "<content id hex>,<index>,<size>",
            # then TMDSize and MaxContentIndex, all read from the pack's TMD.
            import struct
            tdir = "/cdn/%s" % str(req['cas:TitleId']).upper()
            tmd = open(tdir + "/tmd.bin", "rb").read() if os.path.isfile(tdir + "/tmd.bin") else b""
            records = {}
            if len(tmd) >= 0xB04:
                for n in range(struct.unpack(">H", tmd[0x1DE:0x1E0])[0]):
                    cid, cindex, _, csize = struct.unpack(">IHHQ", tmd[0xB04 + n * 0x30:0xB14 + n * 0x30])
                    records[cindex] = (cid, csize)
            body = "".join("<ContentSize>%08X,%d,%d</ContentSize>" % (records.get(i, (i, size))[0], i, records.get(i, (i, size))[1]) for i, size in pairs)
            body += "<TMDSize>%d</TMDSize><MaxContentIndex>%d</MaxContentIndex>" % (len(tmd), max(records) if records else 0)
        r = make_response(render_template("cas/getContentSizes.xml", id=req['cas:DeviceId'], message=req['cas:MessageId'], time=int(round(time.time()*1000)), body=body))
        r.headers.set("Content-Type", "text/xml; charset=utf-8")
        return r
    if "cas:ListItems" in parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']:""")
Path("templates/cas/getContentSizes.xml").write_text("""{% extends 'header.xml' %}{% block main %}<GetContentSizesResponse xmlns="urn:cas.wsapi.broadon.com"><Version>2.0</Version><DeviceId>{{ id }}</DeviceId><MessageId>{{ message }}</MessageId><TimeStamp>{{ time }}</TimeStamp><ErrorCode>0</ErrorCode>{{ body|safe }}</GetContentSizesResponse>{% endblock %}""")

# IAS SetCountry answered OK but never saved the console's new country, so
# a console whose country setting changed (e.g. AN -> VI) kept getting
# 009-1003 "country settings do not match" when buying plays.
patch("ias.py", """            ds = Client3DS.objects.get(consoleid=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ias:SetCountry']['ias:DeviceId'])
        except ObjectDoesNotExist:
            return "Error"
""", """            ds = Client3DS.objects.get(consoleid=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ias:SetCountry']['ias:DeviceId'])
        except ObjectDoesNotExist:
            return "Error"
        country = parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ias:SetCountry'].get('ias:Country')
        if country:
            ds.country = str(country)
            ds.save()
""")

# The Theme Shop lists the themes inside a pack (its optional contents) with
# CAS ListContentSetsEx. Answer from cdn/<title id>/contentsets.json, which
# tools/theme_pack.py writes. Response format as parsed by luigoalma/cleaninty
# (a client for Nintendo's real CAS): one <Contents> per theme with TitleId,
# Contents{TitleIncluded, ContentIndex}, Attributes{Name, Value} and Prices.
# Ratings: the shop asks for them (age-rating check); every theme is ESRB E,
# age 0, in cleaninty's Ratings{Name, Rating, Age, Descriptors} layout.
# Visible themes get no HIDDEN attribute. Limits PR <n> is how many times a
# theme can be bought (in ListTitlesEx PR 0 hid it); in ListContentSetsEx every
# Nintendo answer we have says Limits 0 PR, so content sets send 0 unless the
# theme sets "limit". No Limits makes the shop treat it as already owned.
patch("cas.py", """    if "cas:ListItems" in parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']:""", """    if "cas:ListContentSetsEx" in parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']:
        import json
        req = parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListContentSetsEx']
        tids = req.get('cas:TitleId', [])
        tids = tids if isinstance(tids, list) else [tids]
        wanted = req.get('cas:Attributes', [])
        wanted = wanted if isinstance(wanted, list) else [wanted]
        sets = []
        for tid in [str(t).upper() for t in tids]:
            try:
                themes = json.load(open("/cdn/%s/contentsets.json" % tid))
            except (OSError, ValueError):
                continue
            title = Title.objects.filter(tid=tid).first()
            if title is not None and not title.public:
                continue  # a hidden pack: not listed, also for consoles that installed it before
            for theme in themes:
                # a player's personal theme (tools/add_theme.py --owner): listed for them only;
                # the proxy says who's asking (X-Badgecade-Player, only the proxy sets it)
                if theme.get("owner") and theme["owner"] != request.headers.get("X-Badgecade-Player", ""):
                    continue
                it = item.objects.filter(id=theme["item_id"]).first()
                # sys.ItemCode: the pack's product code without dashes plus the content
                # index (CTRMBCTE00000001, from contentsets.json; Nintendo's answers look
                # like CTRMAXCE00000001); ITEM_CODE is the shop's own number (thmdtls key).
                # sys.AllowContentOverlap is "N" in Nintendo's answers.
                values = {"PUBLISHER_NAME": theme["publisher"], "ITEM_CODE": theme["item_code"],
                          "TitleVersion": str(title.version if title else 0),
                          "sys.ItemCode": theme.get("product_code") or ("CTR-M-B%02d%s" % (theme["index"], {"0004008C00008F": "E", "0004008C000098": "P", "0004008C000082": "J"}.get(tid[:14], "E"))),
                          "sys.AllowContentOverlap": "N",
                          "NewSince": str(theme.get("new_since", 1791504000000)),
                          # the Buy button asks for these too (with sys.ItemCode ==): without
                          # NA_FORMAT_VERSION mint (the Buy window) stops with 009-1400 after
                          # the balance check; "1" as in Nintendo's item data. Size is the
                          # theme's content
                          "NA_FORMAT_VERSION": "1",
                          "MaxUserFileSize": str(os.path.getsize("/cdn/%s/%08X.app" % (tid, theme["index"]))
                                                 if os.path.isfile("/cdn/%s/%08X.app" % (tid, theme["index"])) else 0)}
                attributes = []
                for name in wanted:
                    if str(name).startswith("NA_NAME_"):
                        attributes.append((name, theme["name"]))
                    elif str(name).startswith("NA_ICON_INDEX_"):
                        attributes.append((name, str(theme["icon_index"])))
                    # never empty: mint (the Buy window) crashed (data abort, address 4)
                    # reading an empty disclaimer; Nintendo's are always filled in
                    elif str(name).startswith("NA_DESCRIPTION_SHORT_"):
                        attributes.append((name, theme.get("description") or theme["name"]))
                    elif str(name).startswith("NA_DISCLAIMER_"):
                        attributes.append((name, "* A HOME Menu theme from BadgeCade"))
                    elif name in values:
                        attributes.append((name, values[name]))
                sets.append({"tid": tid, "index": theme["index"], "item_code": theme["item_code"], "attributes": attributes,
                             # Ratings only when asked (the theme list asks, the Buy lookup
                             # doesn't; Nintendo's answers have none): with them mint crashed
                             # (data abort, address 4) once it accepted NA_FORMAT_VERSION 1
                             "ratings": "Ratings" in wanted,
                             "sys_item_code": values["sys.ItemCode"],
                             "item_id": theme["item_id"], "price": theme["price"] if "price" in theme else (it.price if it else 0), "limit": theme.get("limit", 0),
                             "title_included": "true" if theme.get("title_included", True) else "false"})
        # AttributeFiltersEx: the Download button asks for one theme by
        # ITEM_CODE == <theme id>; answering with every theme made it fail
        # ("unable to obtain data") once a pack had two
        filters = req.get('cas:AttributeFiltersEx', [])
        filters = filters if isinstance(filters, list) else [filters]
        # (the Buy button then asks again by sys.ItemCode == <product code + index>;
        # answering with every theme there gave 009-1400)
        for f in filters:
            if not isinstance(f, dict) or f.get('cas:FilterType') != '==':
                continue
            key = {'ITEM_CODE': 'item_code', 'sys.ItemCode': 'sys_item_code'}.get(f.get('cas:Name'))
            if key:
                sets = [x for x in sets if x[key] == str(f.get('cas:Value'))]
        # oldest theme first, newest last (the order they were added: item numbers
        # only go up), whatever order the console asks for (ITEM_CODE descending
        # mixed the packs up, as they fill from 8F08 down to 8F05)
        sets.sort(key=lambda s: int(s["item_id"]))
        offset = int(req.get('cas:ListResultOffset') or 0)
        # the console asks for 200 at a time and shows what it gets: capping the
        # answer at 25 only hid themes (it never asked for the next 25)
        limit = int(req.get('cas:ListResultLimit') or 200)
        r = make_response(render_template("cas/listContentSetsEx.xml", id=req['cas:DeviceId'], message=req['cas:MessageId'], time=int(round(time.time()*1000)), total=len(sets), sets=sets[offset:offset + limit]))
        r.headers.set("Content-Type", "text/xml; charset=utf-8")
        return r
    if "cas:ListItems" in parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']:""")
Path("templates/cas/listContentSetsEx.xml").write_text("""{% extends 'header.xml' %}{% block main %}<ListContentSetsExResponse xmlns="urn:cas.wsapi.broadon.com"><Version>2.0</Version><DeviceId>{{ id }}</DeviceId><MessageId>{{ message }}</MessageId><TimeStamp>{{ time }}</TimeStamp><ErrorCode>0</ErrorCode><ListResultTotalSize>{{ total }}</ListResultTotalSize>{% for s in sets %}<Contents><TitleId>{{ s.tid }}</TitleId><Contents><TitleIncluded>{{ s.title_included }}</TitleIncluded><ContentIndex>{{ s.index }}</ContentIndex></Contents>{% for name, value in s.attributes %}<Attributes><Name>{{ name }}</Name><Value>{{ value }}</Value></Attributes>{% endfor %}{% if s.ratings %}<Ratings><Name>ESRB</Name><Rating>E</Rating><Age>0</Age><Descriptors></Descriptors></Ratings>{% endif %}<Prices><ItemId>{{ s.item_id }}</ItemId><Price><Amount>{{ s.price }}</Amount><Currency>CREDIT</Currency></Price><Limits><Limits>{{ s.limit }}</Limits><LimitKind>PR</LimitKind></Limits><LicenseKind>PERMANENT</LicenseKind></Prices></Contents>{% endfor %}</ListContentSetsExResponse>{% endblock %}""")

# A theme pack's ticket grants content 0 (theme names and icons) and the
# themes this console has bought, not every content (basetik.bin grants
# 0-255, so the Theme Shop thought every theme was already owned and never
# bought or downloaded it). Rights bit field: ticket 0x2D0, 0x80 bytes, one
# bit per content index, lowest bit first (as GodMode9's TicketRightsCheck).
patch("ecs.py", """            modified_tik = tk.getvalue()
""", """            modified_tik = tk.getvalue()
        if is_dlc:
            import json
            try:
                sets = json.load(open("/cdn/%s/contentsets.json" % titleid.upper()))
            except (OSError, ValueError):
                sets = []
            themes = {s["item_id"]: s["index"] for s in sets}
            # free themes too are "bought" (for 0) before they're owned, as with
            # Nintendo; a pack ticket that already granted them made the Theme
            # Shop treat them as owned (a CIA install brings its own ticket).
            # Themes marked granted (or auto_install) are owned by every console.
            # "purchase_test" themes are bought (not granted) by the consoles in
            # /cdn/.test_devices only, to test the free Buy flow without
            # changing the shop for everyone else
            try:
                test_devices = open("/cdn/.test_devices").read().split()
            except OSError:
                test_devices = []
            testing = str(getattr(ds, "consoleid", "")) in test_devices
            indexes = {0} | {s["index"] for s in sets if (s.get("granted") or s.get("auto_install")) and not s.get("owner") and not (testing and s.get("purchase_test"))} | {themes[o.item.id] for o in ownedTicket.objects.filter(owner=ds, item__title=owned.item.title) if o.item.id in themes}
            # personal themes: owned by their player only
            player = request.headers.get("X-Badgecade-Player", "")
            indexes |= {s["index"] for s in sets if s.get("owner") and player and s["owner"] == player}
            rights = bytearray(0x80)  # one rights record: content indexes 0-1023
            for index in indexes:
                if index < 0x400:
                    rights[index // 8] |= 1 << (index % 8)
                else:
                    print("ticket rights: content index %d is past 1023, not granted" % index, flush=True)
            modified_tik = modified_tik[:0x2D0] + bytes(rights) + modified_tik[0x350:]
""")

# Download codes for themes: the Theme Shop's "Enter Download Code" sends
# ninja redeemable_card/!check (card_number, tin, titleId). A card whose
# content is a theme's item code (is_money off) answers as add-on content,
# shaped like the Wii U eShop parses it (ReeShop's woodlibs.js:
# contents.content[0].aoc with the theme's content_indexes).
patch("api/views.py", """   else:
      try:
         title = Title.objects.get(tid=card.content)""", """   else:
      # each region's pack can hold a different theme in the same slot (same item code):
      # take the copy in the asking Theme Shop's region (titleId 8F00 / 9800 / 8200)
      theme_items = list(item.objects.filter(itemcode=card.content, title__tid__istartswith="0004008C"))
      wanted = {"0004000000008F00": "0004008C00008F", "0004000000009800": "0004008C000098",
                "0004000000008200": "0004008C000082"}.get(str(request.POST.get("titleId", "")).upper())
      theme_item = next((i for i in theme_items if wanted and i.title.tid.upper().startswith(wanted)),
                        theme_items[0] if theme_items else None)
      if theme_item is not None:
         import io, json  # this module's view "open" hides the builtin
         try:
            sets = json.load(io.open("/cdn/%s/contentsets.json" % theme_item.title.tid.upper()))
         except (OSError, ValueError):
            sets = []
         theme = next((s for s in sets if s["item_id"] == theme_item.id), None)
         if theme is None:
            return JsonResponse({"error": {"code": "5615", "message": "The corresponding theme was not found.\\nContact an administrator."}}, status=400)
         # what the theme download needs, as a game code gives title_ec_info
         import os as _os
         size = _os.path.getsize("/cdn/%s/%08X.app" % (theme_item.title.tid.upper(), theme["index"])) if _os.path.isfile("/cdn/%s/%08X.app" % (theme_item.title.tid.upper(), theme["index"])) else 0
         ec_info = {"title_id": theme_item.title.tid, "content_size": size, "title_version": theme_item.title.version}
         res = {"redeemable_card": {"number": request.POST.get("card_number"), "reference_title_id": theme_item.title.tid,
                "contents": {"content": [{"aoc": {"id": theme_item.id, "name": theme["name"], "title_id": theme_item.title.tid,
                "data_title_id": theme_item.title.tid, "item_id": theme_item.id, "item_code": theme["item_code"],
                "content_indexes": {"content_index": [theme["index"]], "variation": 0}}}]},
                "title_ec_info": ec_info, "aoc_ec_info": ec_info}}
         return JsonResponse(res)
      try:
         title = Title.objects.get(tid=card.content)""")

# The HOME Menu Theme Shop checks money (shopdeck prices everything in
# "CREDIT" and the ninja balance in "EUR"): its Buy button gave up without a
# request and a theme download code ended in 009-1204 right after the balance.
# Theme Shop requests (the proxy passes the app id in X-Badgecade-App-Id; SOAP
# bodies carry ApplicationId) get the console's real currency everywhere:
# CAS prices, ECS GetAccountStatus balance, ninja balance, country and the
# purchase result. The eShop (plays) keeps credits.
Path("badgecade_money.py").write_text('''"""BadgeCade: money in the console's real currency for the Theme Shop."""

THEME_SHOP_APP = "0004000000008f00"
# the Theme Shop's application id in each region (its theme packs' base: 8F00 USA, 9800 EUR, 8200 JPN)
THEME_SHOP_APPS = {"0004000000008200", THEME_SHOP_APP, "0004000000009800"}
# The Theme Shop shows this wallet, not the plays balance: theme prices are
# for show (nothing is taken), so any price up to the shop's max_cash can be bought
THEME_WALLET = 999


def theme_wallet(ds, headers):
    """What the Theme Shop shows: the player's credits wallet on consoles with
    credits (badgecade_credits; whole credits, themes are free), else THEME_WALLET"""
    import badgecade_credits
    if ds is not None and badgecade_credits.enabled(ds):
        return badgecade_credits.units(badgecade_credits.balance(ds, headers), badgecade_credits.code(ds))
    return THEME_WALLET
_COUNTRY_CURRENCY = {
    "US": "USD", "CA": "CAD", "MX": "MXN", "BR": "BRL", "GB": "GBP", "AU": "AUD", "NZ": "NZD",
    "CH": "CHF", "NO": "NOK", "SE": "SEK", "DK": "DKK", "PL": "PLN", "CZ": "CZK", "HU": "HUF",
    "ZA": "ZAR", "RU": "RUB", "JP": "JPY", "KR": "KRW", "TW": "TWD", "HK": "HKD",
}
_PREFIX = {"USD": "$", "CAD": "$", "AUD": "$", "NZD": "$", "MXN": "$", "BRL": "R$", "GBP": "\\u00a3", "JPY": "\\u00a5", "KRW": "\\u20a9", "TWD": "NT$", "HKD": "HK$"}
_NO_DECIMALS = {"JPY", "KRW", "HUF"}


def is_theme_shop(request=None, app_id=None):
    if app_id is None and request is not None:
        app_id = request.headers.get("X-Badgecade-App-Id")
    return (app_id or "").strip().lower() in THEME_SHOP_APPS


def currency(country, region=None):
    country = (country or "").upper()
    if country in _COUNTRY_CURRENCY:
        return _COUNTRY_CURRENCY[country]
    return {"EUR": "EUR", "JPN": "JPY", "KOR": "KRW"}.get((region or "").upper(), "USD")


def raw(value, code):
    return "%d" % int(value) if code in _NO_DECIMALS else "%.2f" % float(value)


def soap_amount(value, code):
    """CAS/ECS amounts: whole numbers (as in Pretendo's 3DS ECS: Amount '999' USD);
    "0.00" stopped the Theme Shop with 009-1502 right after ListTitlesEx"""
    return "%d" % int(value)


def price_amount(value, code):
    """A theme's price in ListContentSetsEx: whole amounts as before ("0", "3"),
    cents when there are some ("1.99", as Nintendo's content sets: "1.00")"""
    value = float(value)
    if value == int(value) or code in _NO_DECIMALS:
        return "%d" % round(value)
    return "%.2f" % value


def text(value, code):
    amount = raw(value, code)
    return _PREFIX[code] + amount if code in _PREFIX else amount + " " + code


def money(value, code):
    """ninja's {amount, currency, raw_value}"""
    return {"amount": text(value, code), "currency": code, "raw_value": raw(value, code)}


def price_format(code):
    prefix = _PREFIX.get(code, "")
    suffix = "" if prefix else " " + code
    digits = "#,###,###,###" if code in _NO_DECIMALS else "#,###,###,###.##"
    return {"positive_prefix": prefix, "positive_suffix": suffix, "negative_prefix": "-" + prefix,
            "negative_suffix": suffix, "formats": {"format": [{"value": digits, "digit": "#"}], "pattern_id": "5"}}
''')

# ninja balance, country and aoc purchase (wrappers at the end of api/views.py)
Path("api/views.py").write_text(Path("api/views.py").read_text() + '''

import json as _bc_json
import badgecade_money

_badgecade_balance = balance
_badgecade_country = country


def _badgecade_ds(request):
    device = request.session.get("deviceid") or request.headers.get("X-Badgecade-Device-Id")
    return Client3DS.objects.filter(consoleid=str(device)).first() if device else None


@csrf_exempt
def balance(request):
    r = _badgecade_balance(request)
    ds = _badgecade_ds(request)
    if r.status_code == 200 and ds is not None and badgecade_money.is_theme_shop(request):
        return JsonResponse({"balance": badgecade_money.money(badgecade_money.theme_wallet(ds, request.headers), badgecade_money.currency(ds.country, ds.region))})
    return r


@csrf_exempt
def country(request, country):
    r = _badgecade_country(request, country)
    if r.status_code == 200 and badgecade_money.is_theme_shop(request):
        data = _bc_json.loads(r.content)
        code = badgecade_money.currency(country, data["country_detail"].get("region_code"))
        data["country_detail"]["max_cash"] = badgecade_money.money(999, code)
        data["country_detail"]["price_format"] = badgecade_money.price_format(code)
        return JsonResponse(data)
    return r


_badgecade_purchase_aoc = purchase_aoc


@csrf_exempt
def purchase_aoc(request, country, tid):
    r = _badgecade_purchase_aoc(request, country, tid)
    ds = _badgecade_ds(request)
    if r.status_code == 200 and ds is not None and (badgecade_money.is_theme_shop(request) or tid.lower() in badgecade_money.THEME_SHOP_APPS):
        data = _bc_json.loads(r.content)
        for result in data["transaction_results"]["transaction_result"]:
            result["post_balance"] = badgecade_money.money(badgecade_money.theme_wallet(ds, request.headers), badgecade_money.currency(ds.country, ds.region))
        return JsonResponse(data)
    return r
''')
# ECS GetAccountStatus: the balance in the console's currency for the Theme Shop
patch("ecs.py", """        r = make_response(render_template("ecs/getAccountStatus.xml", id=ds.consoleid, message=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:GetAccountStatus']['ecs:MessageId'], time=int(round(time.time()*1000)), accountid=ds.id, balance=ds.balance,""", """        import badgecade_money
        if badgecade_money.is_theme_shop(app_id=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:GetAccountStatus'].get('ecs:ApplicationId')):
            money_code = badgecade_money.currency(ds.country, ds.region)
            money_amount = badgecade_money.soap_amount(badgecade_money.theme_wallet(ds, request.headers), money_code)
        else:
            money_code, money_amount = "CREDIT", ds.balance
            import badgecade_credits  # test consoles: their money wallet (SOAP amounts stay whole)
            if badgecade_credits.enabled(ds):
                money_code = badgecade_credits.code(ds)
                money_amount = badgecade_money.soap_amount(badgecade_credits.units(badgecade_credits.balance(ds, request.headers), money_code), money_code)
        r = make_response(render_template("ecs/getAccountStatus.xml", id=ds.consoleid, message=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:GetAccountStatus']['ecs:MessageId'], time=int(round(time.time()*1000)), accountid=ds.id, balance=money_amount, money_code=money_code,""")
patch("templates/ecs/getAccountStatus.xml", "<Currency>CREDIT</Currency>", "<Currency>{{ money_code }}</Currency>")

# CAS prices (ListTitlesEx, ListContentSetsEx) for the Theme Shop
patch("cas.py", """        r = make_response(render_template("cas/listTitlesEx.xml", id=req['cas:DeviceId'], message=req['cas:MessageId'], time=int(round(time.time()*1000)), titles=titles))""", """        import badgecade_money
        if badgecade_money.is_theme_shop(app_id=req.get('cas:ApplicationId')):
            money_code = badgecade_money.currency(req.get('cas:Country'), req.get('cas:Region'))
            money_fmt = lambda v: badgecade_money.soap_amount(v, money_code)
        else:
            money_code, money_fmt = "CREDIT", str
        r = make_response(render_template("cas/listTitlesEx.xml", id=req['cas:DeviceId'], message=req['cas:MessageId'], time=int(round(time.time()*1000)), titles=titles, money_code=money_code, money_fmt=money_fmt))""")
patch("templates/cas/listTitlesEx.xml", "<Price><Amount>{{ i.price }}</Amount><Currency>CREDIT</Currency></Price>", "<Price><Amount>{{ money_fmt(i.price) }}</Amount><Currency>{{ money_code }}</Currency></Price>")
patch("cas.py", """        r = make_response(render_template("cas/listContentSetsEx.xml", id=req['cas:DeviceId'], message=req['cas:MessageId'], time=int(round(time.time()*1000)), total=len(sets), sets=sets[offset:offset + limit]))""", """        import badgecade_money
        if badgecade_money.is_theme_shop(app_id=req.get('cas:ApplicationId')):
            money_code = badgecade_money.currency(req.get('cas:Country'), req.get('cas:Region'))
            money_fmt = lambda v: badgecade_money.price_amount(v, money_code)
        else:
            money_code, money_fmt = "CREDIT", str
        r = make_response(render_template("cas/listContentSetsEx.xml", id=req['cas:DeviceId'], message=req['cas:MessageId'], time=int(round(time.time()*1000)), total=len(sets), sets=sets[offset:offset + limit], money_code=money_code, money_fmt=money_fmt))""")
patch("templates/cas/listContentSetsEx.xml", "<Price><Amount>{{ s.price }}</Amount><Currency>CREDIT</Currency></Price>", "<Price><Amount>{{ money_fmt(s.price) }}</Amount><Currency>{{ money_code }}</Currency></Price>")

# A SOAP request shopdeck has no handler for (e.g. ECS CheckECard, sent when a
# player types an eShop card code; 2026-10-09 17:17 UTC) fell off the end of
# soap(): the view returned None and Flask answered 500, which the console
# shows as a connection error. Every SOAP view (all three end inside soap())
# now ends with a proper <Action>Response carrying an error code instead,
# and logs "UNSUPPORTED SOAP" so it shows up in the Discord digest.
Path("badgecade_soap.py").write_text('''"""BadgeCade: answer SOAP actions shopdeck doesn't implement."""
import time

from flask import make_response

UNSUPPORTED = 1  # generic failure; the console shows its own error code


def unsupported(parsed, service):
    body = parsed["SOAP-ENV:Envelope"]["SOAP-ENV:Body"]
    key = next((k for k in body if str(k).startswith(service + ":")), service + ":Unknown")
    action = key.split(":", 1)[1]
    request = body.get(key) if isinstance(body.get(key), dict) else {}
    device = request.get(service + ":DeviceId", "")
    message = request.get(service + ":MessageId", "")
    print("UNSUPPORTED SOAP %s:%s device=%s" % (service, action, device), flush=True)
    xml = ('<?xml version="1.0" encoding="utf-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
           'xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><soapenv:Body>'
           '<%sResponse xmlns="urn:%s.wsapi.broadon.com"><Version>2.0</Version><DeviceId>%s</DeviceId><MessageId>%s</MessageId>'
           '<TimeStamp>%d</TimeStamp><ErrorCode>%d</ErrorCode><ErrorMessage>Not supported on BadgeCade</ErrorMessage>'
           '</%sResponse></soapenv:Body></soapenv:Envelope>') % (action, service, device, message, int(time.time() * 1000), UNSUPPORTED, action)
    response = make_response(xml)
    response.headers.set("Content-Type", "text/xml; charset=utf-8")
    return response
''')
for _path, _service in (("ecs.py", "ecs"), ("cas.py", "cas"), ("ias.py", "ias")):
    _source = Path(_path).read_text().rstrip()
    assert _source.endswith("return r"), f"{_path} changed upstream: soap() no longer ends the file"
    Path(_path).write_text(_source + "\n    return __import__('badgecade_soap').unsupported(parsed, '%s')\n" % _service)

# IAS only accepted the eShop's user agent ("CTR EC"), so the system update
# check's IAS GetChallenge ("CTR NUP", sent when a console's saved update hash
# differs, e.g. right after a system update) got "Error" and the shop stopped
# with 009-6517. ECS already accepts both.
patch("ias.py", """    if request.headers.get('User-Agent') != "CTR EC 040600 Mar 14 2012 13:32:39":
        return "Error\"""", """    if request.headers.get('User-Agent') not in ("CTR EC 040600 Mar 14 2012 13:32:39", "CTR NUP 040600 Mar 14 2012 13:32:39"):
        return "Error\"""")

# A plays ticket was deleted as soon as it was sent. If the console crashed
# or lost the connection before saving it (HOME pressed mid-purchase, Wi-Fi
# drop), asking again got "Error" and the bought plays were gone. Keep each
# sent plays ticket in /data/sent_tickets for a day and hand the same bytes
# back if the console asks for it again; it's the same ticket id, so the
# console can't get the plays twice.
patch("ecs.py", """        if istitle == False and istik==False:
            return "Error\"""", """        if istitle == False and istik==False:
            import glob, os as _os
            tid_hex = '{:016x}'.format(int(parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:AccountGetETickets']['ecs:TicketId']))
            for old in glob.glob("/data/sent_tickets/*.tik"):
                if time.time() - _os.path.getmtime(old) > 86400:
                    _os.remove(old)
            sent = "/data/sent_tickets/%s-%s.tik" % (ds.consoleid, tid_hex)
            if not _os.path.exists(sent):
                return "Error"
            print("Sending ticket again (console didn't keep it)...")
            r = make_response(render_template("ecs/getAccountETickets.xml", id=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:AccountGetETickets']['ecs:DeviceId'], message=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:AccountGetETickets']['ecs:MessageId'],time=int(round(time.time()*1000)), tik=base64.b64encode(open(sent, "rb").read()).decode('utf-8')))
            r.headers.set("Content-Type", "text/xml; charset=utf-8")
            return r""")
patch("ecs.py", """            owned = ownedTicket.objects.get(ticketid='{:016x}'.format(int(parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:AccountGetETickets']['ecs:TicketId'])), owner=ds)
            istik = True""", """            # a theme pack's purchases share one ticket id (pack_ticketid in api/views.py)
            owned = ownedTicket.objects.filter(ticketid='{:016x}'.format(int(parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['ecs:AccountGetETickets']['ecs:TicketId'])), owner=ds).order_by("id").first()
            if owned is None:
                raise ObjectDoesNotExist
            istik = True""")
patch("ecs.py", """        if istik and not is_dlc:
            owned.delete()""", """        if istik and not is_dlc:
            import os as _os
            _os.makedirs("/data/sent_tickets", exist_ok=True)
            with open("/data/sent_tickets/%s-%s.tik" % (ds.consoleid, owned.ticketid), "wb") as f:
                f.write(modified_tik)
            owned.delete()""")

# Bonus theme offer, like Nintendo's Badge Arcade campaigns: buy enough plays
# between the offer's start and end and a theme is given as a present. The
# offer is set on the theme admin page (/cdn/bonus.json: item_id, plays,
# start, end, id); each console's plays bought during an offer are counted in
# /data/bonus_progress.json. A given theme is an owned ticket for its item,
# so the pack ticket grants it and the Theme Shop shows it as owned.
patch("api/views.py", """   # the price is only shown; plays never take the balance
   owned = ownedTicket.objects.create(item=aitem, ticketid=(b'\\x00\\x04'+ os.urandom(6)).hex(), owner=ds)
   res = {"transaction_results": {"transaction_result":[{"transaction_id":owned.pk,""", """   # the price is only shown; plays never take the balance
   owned = ownedTicket.objects.create(item=aitem, ticketid=(b'\\x00\\x04'+ os.urandom(6)).hex(), owner=ds)
   try:
      _bonus_count(ds, aitem)
   except Exception as error:  # never let the offer break a purchase
      print("bonus offer: %r" % (error,), flush=True)
   res = {"transaction_results": {"transaction_result":[{"transaction_id":owned.pk,""")
Path("api/views.py").write_text(Path("api/views.py").read_text() + '''

# --- badgecade: bonus theme offer ---
PLAYS_PER_PURCHASE = 5


def _bundle_plays(aitem):
   """Nintendo's play bundles: CTRVJWVE0000000N (USA, P = EUR, J = JPN) is 5 x N plays."""
   code = aitem.itemcode or ""
   if code.startswith("CTRVJWV") and code[-1:].isdigit():
      return PLAYS_PER_PURCHASE * int(code[-1])
   return PLAYS_PER_PURCHASE


def _bonus_offers():
   """cdn/bonus.json: {"offers": [...]} (the first version held one offer)."""
   import io, json
   try:
      data = json.load(io.open("/cdn/bonus.json"))
   except (OSError, ValueError):
      return []
   return data.get("offers", []) if "offers" in data else [data]


def _holiday_day(key, year):
   """The holiday's date in a year (same list as tools/theme_admin.py HOLIDAYS)."""
   import datetime
   if key == "easter":
      a, b, c = year % 19, year // 100, year % 100
      d, e = divmod(b, 4)
      h = (19 * a + b - d - (8 * b + 13) // 25 + 15) % 30
      i, k = divmod(c, 4)
      l = (32 + 2 * e + 2 * i - h - k) % 7
      m = (a + 11 * h + 22 * l) // 451
      month, day = divmod(h + l - 7 * m + 114, 31)
      return datetime.date(year, month, day + 1)
   if key == "thanksgiving":
      first = datetime.date(year, 11, 1)
      return first + datetime.timedelta(days=(3 - first.weekday()) % 7 + 21)
   month, day = {"newyear": (1, 1), "valentine": (2, 14), "halloween": (10, 31), "christmas": (12, 25)}[key]
   return datetime.date(year, month, day)


def _holiday_window(offer, today):
   """An every-year offer's window (start, end, year) running today, else its next one."""
   import datetime
   start, end = datetime.date.fromisoformat(offer["start"]), datetime.date.fromisoformat(offer["end"])
   base = _holiday_day(offer["holiday"], int(offer["holiday_year"]))
   for year in range(today.year - 1, today.year + 2):
      day = _holiday_day(offer["holiday"], year)
      window = (day + (start - base), day + (end - base), year)
      if window[1] >= today:
         return window
   return window


def _running_offers(today, region="USA"):
   """[(offer, progress key prefix)] for the offers on today. An offer that comes
   with a badge set runs on its set's days in the region's hall (set_windows,
   worked out by tools/set_offers.py), each window counted apart."""
   import datetime
   running = []
   for o in _bonus_offers():
      if not o.get("enabled"):
         continue
      if o.get("set"):
         window = (o.get("set_windows") or {}).get(region)
         if not window:
            continue
         start, end = datetime.date.fromisoformat(window[0]), datetime.date.fromisoformat(window[1])
         key = "%s@%s" % (o["id"], window[0])
      elif o.get("yearly"):
         start, end, year = _holiday_window(o, today)
         key = "%s@%s" % (o["id"], year)
      else:
         start, end = datetime.date.fromisoformat(o["start"]), datetime.date.fromisoformat(o["end"])
         key = o["id"]
      if start <= today <= end:
         running.append((o, key))
   return running


def _bonus_count(ds, aitem):
   import datetime, fcntl, io, json
   if not aitem.title.tid.upper().startswith("0004000D"):
      return
   # the offer names the USA theme; EUR and JPN copies of a theme are its item + 100000 / + 200000
   offset = {"0004000D00153600": 100000, "0004000D00134600": 200000}.get(aitem.title.tid.upper(), 0)
   running = _running_offers(datetime.datetime.utcnow().date(), {100000: "EUR", 200000: "JPN"}.get(offset, "USA"))
   if not running:
      return
   with io.open("/data/bonus_progress.json", "a+") as f:
      fcntl.flock(f, fcntl.LOCK_EX)
      f.seek(0)
      try:
         progress = json.loads(f.read() or "{}")
      except ValueError:
         progress = {}
      for offer, key in running:
         key = "%s:%s" % (key, ds.consoleid)
         progress[key] = progress.get(key, 0) + _bundle_plays(aitem)
      f.seek(0)
      f.truncate()
      json.dump(progress, f)
   for offer, key in running:
      if progress["%s:%s" % (key, ds.consoleid)] < int(offer["plays"]):
         continue
      prize = item.objects.filter(id=int(offer["item_id"]) + offset).first()
      if prize is None:
         print("bonus offer: no item %s (theme not sold in this region)" % (int(offer["item_id"]) + offset), flush=True)
      elif not ownedTicket.objects.filter(item=prize, owner=ds).exists():
         ownedTicket.objects.create(item=prize, ticketid=(b'\\x00\\x04' + os.urandom(6)).hex(), owner=ds)
         pack_ticketid(ds, prize)  # into the pack's one ticket
         print("bonus offer: console %s got %s" % (ds.consoleid, offer.get("name", prize.id)), flush=True)


# A "winners only" offer's theme can't be bought: Buy answers with a message
# (consoles that won it already own it, so they never press Buy). Applies to
# every region's copy of the theme while the offer is on the admin page.
_bonus_purchase_aoc = purchase_aoc


@csrf_exempt
def purchase_aoc(request, country, tid):
   try:
      wanted = int(request.POST.get("item_id[]")) % 100000
   except (TypeError, ValueError):
      wanted = None
   if wanted is not None and any(o.get("exclusive") and int(o["item_id"]) == wanted for o in _bonus_offers()):
      ds = _badgecade_ds(request)
      if ds is None or not ownedTicket.objects.filter(item__id=int(request.POST.get("item_id[]")), owner=ds).exists():
         return JsonResponse({"error": {"code": "2404", "message": "This theme is a Badge Arcade bonus.\\nBuy plays in Badge Arcade during\\nthe offer to get it."}}, status=400)
   return _bonus_purchase_aoc(request, country, tid)
''')

# The account's ticket list (AccountListETicketIds) named only game tickets,
# never the theme packs' (ownedTicket for 0004008C titles). The eShop library
# in Badge Arcade syncs the console's tickets against this list when the
# play shop opens; with the pack's ticket missing from it, the HOME Menu
# dropped the theme in use after leaving Badge Arcade, until the Theme Shop
# (which fetches the pack ticket again right after its own sync) was opened.
# Every pack ticket shopdeck makes grants all the console's themes, so the
# console can fetch any of them.
patch("ecs.py", """customtid=ctid, owned=owned, int=int))
        r.headers.set("Content-Type", "text/xml; charset=utf-8")
        return r
    if 'ecs:DeleteSavedCard'""", """customtid=ctid, owned=owned, int=int, packs=list({t.ticketid: t for t in ownedTicket.objects.filter(owner=ds, item__title__tid__istartswith="0004008C")}.values())))
        r.headers.set("Content-Type", "text/xml; charset=utf-8")
        return r
    if 'ecs:DeleteSavedCard'""")
patch("templates/ecs/accountListETicketIds.xml", """{% for tik in owned %}<TIV>{{ int(tik.ticketid, base=16) }}.0</TIV>{% endfor %}""",
      """{% for tik in owned %}<TIV>{{ int(tik.ticketid, base=16) }}.0</TIV>{% endfor %}{% for tik in packs %}<TIV>{{ int(tik.ticketid, base=16) }}.0</TIV>{% endfor %}""")

# ninja titles/id_pair (title id -> eShop ns_uid): the EU Theme Shop asks it as it
# opens, for Badge Arcade's update title (0004000E00153600), and shopdeck's
# stock answer was error 6569 ("Due to technical limitations, this functionality
# is not available", 026-6569 on European consoles). Answer each title id with a
# stable ns_uid in the CTR range (5001...), as Nintendo's server did.
patch("api/views.py", """@csrf_exempt
def id_pair(request):
   return JsonResponse({"error": {"code": "6569", "message": "Due to technical limitations,\\nthis functionnality is not available."}}, status=401)""", """@csrf_exempt
def id_pair(request):
   import zlib
   ids = request.GET.getlist("title_id[]") or request.GET.getlist("title_id")
   pairs = []
   for tid in ids:
      tid = str(tid).upper()
      found = Title.objects.filter(tid__iexact=tid).first()
      ns_uid = found.id if found else 50010000000000 + zlib.crc32(tid.encode()) % 10000000
      pairs.append({"ns_uid": ns_uid, "title_id": tid, "type": "T"})
   return JsonResponse({"title_id_pairs": {"title_id_pair": pairs}})""")

# eShop storefront (tools/eshop_titles.py): store pages list only applications
# (title ids 00040000...). Theme packs (0004008C...) and Badge Arcade's play
# tickets (0004000D...) are Title rows too, public for the Theme Shop and the
# play shop, but they aren't eShop titles.
replace_all("metadata/views.py", "Title.objects.filter(", 'Title.objects.filter(tid__startswith="00040000", ')

# eShop titles from encrypted homebrew CIAs (tools/eshop_titles.py): the console
# decrypts their contents with the title key in the CIA's own ticket, kept as
# /cdn/<title id>/cetk; that ticket is the base here instead of basetik.bin
# (the console, ticket and account ids are written into it as usual).
patch("ecs.py", """        if istitle or is_dlc:
            with open("basetik.bin", "rb") as f:
                ticket_bytes = f.read()""", """        own_ticket = "/cdn/%s/cetk" % owned.title.tid.upper() if istitle else ""
        if own_ticket and os.path.isfile(own_ticket):
            with open(own_ticket, "rb") as f:
                ticket_bytes = f.read()
        elif istitle or is_dlc:
            with open("basetik.bin", "rb") as f:
                ticket_bytes = f.read()""")

# BadgeCade credits with tax (2026-10-14, user asked to show AND charge tax):
# each console has a wallet in hundredths of a credit (/data/credits.json);
# a play bundle costs its price plus the region's tax, shown like the US
# eShop (prices before tax, then a tax line). The player picks in Miiverse
# Settings whether the wallet refills every day (to ALLOWANCE) or never runs
# out (refilled after each purchase); the proxy passes it as
# X-Badgecade-Credits. Only consoles in /cdn/.test_devices for now: everyone
# else keeps free, tax-free plays until this is tested on a console.
Path("badgecade_credits.py").write_text('''"""BadgeCade: money wallets in the console's currency, with tax (test consoles first)."""
import builtins, datetime, fcntl, json, os

WALLETS = "/data/credits.json"
ALLOWANCE = 1500            # hundredths: 15 credits a day
RATES = {"USA": 8, "EUR": 20, "JPN": 10}   # tax in percent by the console's region
# "Refill every day" bonuses (2026-10-15): a streak of days in a row, and the
# player's birthday (X-Badgecade-Birthday "MM-DD", set once in Miiverse My Menu)
STREAK_BONUS = ((7, 500), (3, 200))   # 7+ days in a row: +5.00, 3+: +2.00
BIRTHDAY_BONUS = 1000                 # +10.00 on your birthday
TAX_TYPE = {"USA": "SALES", "EUR": "VAT", "JPN": "CONSUMPTION"}


def enabled(ds):
    """Every console since 2026-10-15 (was /cdn/.test_devices only)."""
    return ds is not None


def mode(headers):
    value = (headers.get("X-Badgecade-Credits") or "").strip().lower()
    return value if value in ("daily", "unlimited") else "daily"


def rate(ds):
    return RATES.get((getattr(ds, "region", "") or "USA").upper(), 8)


def tax(ds, price_credits):
    """(tax, total) in hundredths for a price in whole credits."""
    cents = int(price_credits) * 100
    t = (cents * rate(ds) + 50) // 100
    return t, cents + t


def _update(ds, change):
    os.makedirs(os.path.dirname(WALLETS), exist_ok=True)
    with builtins.open(WALLETS, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            data = json.loads(f.read() or "{}")
        except ValueError:
            data = {}
        key = str(ds.consoleid)
        wallet = data.get(key) or {"cents": ALLOWANCE, "day": ""}
        result = change(wallet)
        data[key] = wallet
        f.seek(0)
        f.truncate()
        f.write(json.dumps(data, indent=1))
    return result


def birthday(headers):
    value = (headers.get("X-Badgecade-Birthday") or "").strip()
    return value if len(value) == 5 and value[2] == "-" and value.replace("-", "").isdigit() else ""


def _refill(wallet, how, born=""):
    now = datetime.datetime.utcnow().date()
    today = now.isoformat()
    if wallet.get("day") != today:  # a new day: the streak goes on or starts again
        yesterday = (now - datetime.timedelta(days=1)).isoformat()
        wallet["streak"] = wallet.get("streak", 0) + 1 if wallet.get("day") == yesterday else 1
    if how == "unlimited":
        wallet["cents"] = ALLOWANCE   # never run out: always the full allowance
        wallet["day"] = today
    elif wallet.get("day") != today:
        bonus = next((b for days, b in STREAK_BONUS if wallet["streak"] >= days), 0)
        if born and born == now.strftime("%m-%d"):
            bonus += BIRTHDAY_BONUS
        wallet["bonus"] = bonus
        if wallet["cents"] < ALLOWANCE + bonus:
            wallet["cents"] = ALLOWANCE + bonus
        wallet["day"] = today


def balance(ds, headers):
    """The wallet in hundredths (refilled first, as the player chose)."""
    def look(wallet):
        _refill(wallet, mode(headers), birthday(headers))
        return wallet["cents"]
    return _update(ds, look)


def charge(ds, headers, price_credits, taxed=True):
    """Take price (+ tax unless taxed=False: themes); (ok, wallet after) in hundredths."""
    total = tax(ds, price_credits)[1] if taxed else int(price_credits) * 100
    how = mode(headers)
    def take(wallet):
        _refill(wallet, how, birthday(headers))
        if wallet["cents"] < total:
            return False, wallet["cents"]
        wallet["cents"] -= total
        after = wallet["cents"]
        if how == "unlimited":
            wallet["cents"] = ALLOWANCE
        return True, after
    return _update(ds, take)


def code(ds):
    """The wallet's currency: the console's own (USD, EUR, GBP, JPY...)."""
    import badgecade_money
    return badgecade_money.currency(getattr(ds, "country", ""), getattr(ds, "region", ""))


def units(cents, currency):
    """The wallet keeps hundredths; currencies without cents (yen) count them as whole
    units, so 15.00 a day is $15.00 / 15.00 EUR / 1500 JPY and a 1-unit price is 100 JPY."""
    import badgecade_money
    return int(cents) if currency in badgecade_money._NO_DECIMALS else int(cents) / 100


def text(cents, currency="USD"):
    import badgecade_money
    return badgecade_money.text(units(cents, currency), currency)


def raw(cents, currency="USD"):
    import badgecade_money
    return badgecade_money.raw(units(cents, currency), currency)


def money(cents, currency="USD"):
    import badgecade_money
    return badgecade_money.money(units(cents, currency), currency)


def theme_cents(aitem):
    """A theme's exact price in hundredths ($1.99 -> 199), from its pack's contentsets.json."""
    try:
        sets = json.load(builtins.open("/cdn/%s/contentsets.json" % aitem.title.tid.upper()))
        price = next((float(x.get("price", 0)) for x in sets if x["item_id"] == aitem.id), float(aitem.price))
    except (OSError, ValueError):
        price = float(aitem.price)
    return int(round(price * 100))


def tax_cents(ds, cents):
    """(tax, total) in hundredths for an exact amount."""
    t = (int(cents) * rate(ds) + 50) // 100
    return t, int(cents) + t


def charge_cents(ds, headers, cents):
    """Take an exact amount (a theme's price, no tax); (ok, wallet after) in hundredths."""
    how = mode(headers)
    def take(wallet):
        _refill(wallet, how, birthday(headers))
        if wallet["cents"] < cents:
            return False, wallet["cents"]
        wallet["cents"] -= cents
        after = wallet["cents"]
        if how == "unlimited":
            wallet["cents"] = ALLOWANCE
        return True, after
    return _update(ds, take)
''')

patch("api/views.py", "print(\"API (Ninja) Starting Up\")", "print(\"API (Ninja) Starting Up\")\nimport badgecade_credits")
with Path("api/views.py").open("a") as views:
    views.write('''

# --- BadgeCade credits with tax (badgecade_credits.py), test consoles only ---
import json as _bc_json
_bc_country, _bc_balance_view, _bc_purchase_ticket = country, balance, purcahse_ticket


def _bc_ds(request):
    try:
        return Client3DS.objects.get(consoleid=request.session["deviceid"])
    except Exception:
        return None


@csrf_exempt
def country(request, country):
    r = _bc_country(request, country)
    ds = _bc_ds(request)
    if ds is not None and badgecade_credits.enabled(ds):
        data = _bc_json.loads(r.content)
        data["country_detail"]["tax_free_country"] = False  # prices before tax, a tax line at checkout
        cur = badgecade_credits.code(ds)  # money in the console's currency, not credits
        data["country_detail"]["max_cash"] = badgecade_money.money(999, cur)
        data["country_detail"]["price_format"] = badgecade_money.price_format(cur)
        return JsonResponse(data)
    return r


@csrf_exempt
def balance(request):
    r = _bc_balance_view(request)
    ds = _bc_ds(request)
    if ds is not None and badgecade_credits.enabled(ds) and r.status_code == 200 and b"balance" in r.content \
            and not badgecade_money.is_theme_shop(request):
        data = _bc_json.loads(r.content)
        if "balance" in data and isinstance(data["balance"], dict):
            data["balance"] = badgecade_credits.money(badgecade_credits.balance(ds, request.headers), badgecade_credits.code(ds))
            return JsonResponse(data)
    return r


@csrf_exempt
def purcahse_ticket(request, country, tid):
    ds = _bc_ds(request)
    if ds is None or not badgecade_credits.enabled(ds):
        return _bc_purchase_ticket(request, country, tid)
    try:
        aitem = item.objects.get(id=int(request.POST.get("item_id[]")))
    except Exception:
        return _bc_purchase_ticket(request, country, tid)
    ok, after = badgecade_credits.charge(ds, request.headers, aitem.price)
    if not ok:
        return JsonResponse({"error": {"code": "8167", "message": "You don't have enough money for that.\\nYour wallet refills tomorrow."}})
    r = _bc_purchase_ticket(request, country, tid)
    try:
        data = _bc_json.loads(r.content)
        for result in data.get("transaction_results", {}).get("transaction_result", []):
            result["post_balance"] = badgecade_credits.money(after, badgecade_credits.code(ds))
        cur = badgecade_credits.code(ds)
        print("wallet: console %s paid %s (%s, %s mode), %s left" % (ds.consoleid, badgecade_credits.text(aitem.price * 100, cur),
              badgecade_credits.text(badgecade_credits.tax(ds, aitem.price)[1], cur), badgecade_credits.mode(request.headers),
              badgecade_credits.text(after, cur)), flush=True)
        return JsonResponse(data, status=r.status_code)
    except Exception:
        return r
''')

# GetTaxes (the purchase screen's tax line): the tax on test consoles, 0 elsewhere
patch("ecs.py", """country=ds.country, itemid=aitem.id, itemprice=aitem.price))""", """country=ds.country, itemid=aitem.id, itemprice=aitem.price, **_bc_taxes(ds, aitem.price, aitem)))""")
with Path("ecs.py").open("a") as ecs_file:
    ecs_file.write('''


def _bc_taxes(ds, price, aitem=None):
    """GetTaxes amounts (badgecade_credits.py): real tax on test consoles; none on themes."""
    import badgecade_credits
    is_theme = aitem is not None and str(aitem.title.tid).upper().startswith("0004008C")
    if badgecade_credits.enabled(ds) and is_theme and badgecade_credits.theme_cents(aitem) > 0:
        # priced themes: their exact price plus the region's tax, like the plays
        # (free themes keep whole zeros: "0.00" stopped the Theme Shop before)
        cur = badgecade_credits.code(ds)
        cents = badgecade_credits.theme_cents(aitem)
        t, total = badgecade_credits.tax_cents(ds, cents)
        return {"tax": badgecade_credits.raw(t, cur), "pretax": badgecade_credits.raw(cents, cur),
                "aftertax": badgecade_credits.raw(total, cur), "currency": cur, "rate": "%.1f" % badgecade_credits.rate(ds),
                "excluded": "true", "taxtype": badgecade_credits.TAX_TYPE.get((getattr(ds, "region", "") or "USA").upper(), "VAT")}
    if not badgecade_credits.enabled(ds) or is_theme:
        cur = badgecade_credits.code(ds) if badgecade_credits.enabled(ds) else "CREDIT"
        whole = str(price * 100 if cur in ("JPY", "KRW", "HUF") else price)  # themes: whole amounts (the Theme Shop stops on decimals)
        return {"tax": "0", "pretax": whole, "aftertax": whole, "rate": "0.0", "taxtype": "VAT", "excluded": "true", "currency": cur} \
            if badgecade_credits.enabled(ds) else \
            {"tax": "0.00", "pretax": "%d.00" % price, "aftertax": "%d.00" % price, "rate": "0.0", "taxtype": "VAT", "excluded": "true", "currency": cur}
    cur = badgecade_credits.code(ds)
    t, total = badgecade_credits.tax(ds, price)
    return {"tax": badgecade_credits.raw(t, cur), "pretax": badgecade_credits.raw(price * 100, cur), "aftertax": badgecade_credits.raw(total, cur), "currency": cur,
            "rate": "%.1f" % badgecade_credits.rate(ds), "excluded": "true",
            "taxtype": badgecade_credits.TAX_TYPE.get((getattr(ds, "region", "") or "USA").upper(), "VAT")}
''')
Path("templates/ecs/getTaxes.xml").write_text("""{% extends 'header.xml' %}{% block main %}<GetTaxesResponse xmlns="urn:ecs.wsapi.broadon.com"><Version>2.0</Version><DeviceId>{{ id }}</DeviceId><MessageId>{{ message }}</MessageId><TimeStamp>{{ time }}</TimeStamp><ErrorCode>0</ErrorCode><ServiceStandbyMode>false</ServiceStandbyMode><LocationTaxes><TaxLocationId>71662</TaxLocationId><Description>{{ country }}</Description><ItemTaxes><ItemId>{{ itemid }}</ItemId><TaxCategory>DD</TaxCategory><TotalTax>{{ tax }}</TotalTax><PreTaxAmount>{{ pretax }}</PreTaxAmount><AfterTaxAmount>{{ aftertax }}</AfterTaxAmount><Taxes><TaxType>{{ taxtype }}</TaxType><TaxAmount>{{ tax }}</TaxAmount><TaxRate>{{ rate }}</TaxRate></Taxes><Discounts>0</Discounts></ItemTaxes><TaxGrandTotal>{{ tax }}</TaxGrandTotal><PreTaxGrandTotal>{{ pretax }}</PreTaxGrandTotal><AfterTaxGrandTotal>{{ aftertax }}</AfterTaxGrandTotal><DiscountsTotal>0.00</DiscountsTotal><Currency>{{ currency }}</Currency><TaxExcluded>{{ excluded }}</TaxExcluded></LocationTaxes></GetTaxesResponse>{% endblock %}""")


# Theme Shop purchases take money too (test consoles with a wallet,
# badgecade_credits.py): a priced theme costs its exact price ($1.99) plus the
# region's tax, from the same wallet as Badge Arcade's plays (the Theme Shop stops on
# decimal amounts). The wallet is checked first and charged only once the
# purchase went through; free and bonus themes stay free.
with Path("api/views.py").open("a") as views:
    views.write('''

# --- BadgeCade credits in the Theme Shop ---
_bc_theme_purchase_aoc = purchase_aoc


@csrf_exempt
def purchase_aoc(request, country, tid):
    ds = _bc_ds(request)
    if ds is None or not badgecade_credits.enabled(ds):
        return _bc_theme_purchase_aoc(request, country, tid)
    try:
        ids = [int(i) for i in request.POST.getlist("item_id[]")]
    except ValueError:
        ids = []
    # the themes' exact prices ($1.99) plus the region's tax, as at checkout (GetTaxes)
    price_cents = sum(badgecade_credits.theme_cents(it) for it in item.objects.filter(id__in=ids, title__tid__istartswith="0004008C"))
    cents = badgecade_credits.tax_cents(ds, price_cents)[1] if price_cents > 0 else 0
    if cents <= 0:
        return _bc_theme_purchase_aoc(request, country, tid)
    if badgecade_credits.balance(ds, request.headers) < cents:
        return JsonResponse({"error": {"code": "8167", "message": "You don't have enough money for this theme.\\nYour wallet refills tomorrow."}})
    r = _bc_theme_purchase_aoc(request, country, tid)
    if r.status_code != 200 or b"transaction_results" not in r.content:
        return r  # not bought: nothing taken
    ok, after = badgecade_credits.charge_cents(ds, request.headers, cents)
    try:
        data = _bc_json.loads(r.content)
        for result in data.get("transaction_results", {}).get("transaction_result", []):
            result["post_balance"] = badgecade_credits.money(after, badgecade_credits.code(ds))
        cur = badgecade_credits.code(ds)
        print("wallet: console %s bought theme items %s for %s, %s left"
              % (ds.consoleid, ids, badgecade_credits.text(cents, cur), badgecade_credits.text(after, cur)), flush=True)
        return JsonResponse(data, status=r.status_code)
    except Exception:
        return r
''')


# Badge Arcade's play bundles (CAS ListItems) priced in the wallet's currency on
# wallet consoles ($1-$4, as Nintendo's); everyone else keeps "CREDIT"
patch("cas.py", """        r = make_response(render_template("cas/listItems.xml", id=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListItems']['cas:DeviceId'], message=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListItems']['cas:MessageId'],time=int(round(time.time()*1000)), items=items, length=length))""", """        import badgecade_credits, badgecade_money
        _li_ds = Client3DS.objects.filter(consoleid=str(parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListItems']['cas:DeviceId'])).first()
        if _li_ds is not None and badgecade_credits.enabled(_li_ds):
            money_code = badgecade_credits.code(_li_ds)
            money_fmt = lambda v: badgecade_money.soap_amount(badgecade_credits.units(int(v) * 100, money_code), money_code)
        else:
            money_code, money_fmt = "CREDIT", str
        r = make_response(render_template("cas/listItems.xml", id=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListItems']['cas:DeviceId'], message=parsed['SOAP-ENV:Envelope']['SOAP-ENV:Body']['cas:ListItems']['cas:MessageId'],time=int(round(time.time()*1000)), items=items, length=length, money_code=money_code, money_fmt=money_fmt))""")
patch("templates/components/item.xml", "<Price><Amount>{{ item.price }}</Amount><Currency>CREDIT</Currency></Price>",
      "<Price><Amount>{{ money_fmt(item.price) if money_fmt else item.price }}</Amount><Currency>{{ money_code or 'CREDIT' }}</Currency></Price>")
