"""Headless tests: real core logic + GUI code driven through a fake tkinter."""
import sys, types, json, tempfile, shutil, os
from datetime import date, timedelta
from pathlib import Path

# ---------- fake tkinter ----------
class Var:
    def __init__(self, master=None, value=""): self.v=value; self.cbs=[]
    def get(self): return self.v
    def set(self, x):
        self.v=x
        for cb in self.cbs: cb()
    def trace_add(self, mode, cb): self.cbs.append(lambda: cb())
class W:
    def __init__(self,*a,**k): self.kw=k; self.rows={}; self.sel=[]; self.tags={}
    def __getattr__(self,n):
        return lambda *a,**k: W()
class Tree(W):
    def insert(self,parent,idx,iid=None,tags=(),values=()): self.rows[iid]=values
    def delete(self,*ids): self.rows.clear()
    def get_children(self,*a): return list(self.rows)
    def selection(self): return tuple(self.sel)
    def selection_set(self,ids): self.sel=list(ids if isinstance(ids,(list,tuple)) else [ids])
    def identify_row(self,y): return ""
class Canvas(W):
    def __init__(self,*a,**k): super().__init__(); self.items=0
    def create_text(self,*a,**k): self.items+=1
    def create_arc(self,*a,**k): self.items+=1
    def create_oval(self,*a,**k): self.items+=1
    def create_rectangle(self,*a,**k): self.items+=1
    def delete(self,*a): self.items=0
class FontObj:
    def configure(self,**k): pass
    def actual(self,k): return "Arial"
tk=types.ModuleType("tkinter"); ttk=types.ModuleType("tkinter.ttk")
mb=types.ModuleType("tkinter.messagebox"); fd=types.ModuleType("tkinter.filedialog"); fnt=types.ModuleType("tkinter.font")
for n in ("Tk","Menu","Label","Toplevel"): setattr(tk,n,W)
tk.StringVar=Var; tk.Canvas=Canvas; tk.Entry=W; tk.TclError=Exception
for n in ("Frame","Label","Button","Entry","Combobox","Radiobutton","Notebook","Scrollbar","Style","Progressbar"): setattr(ttk,n,W)
ttk.Treeview=Tree
calls=[]
mb.askyesno=lambda *a,**k:(calls.append(("yn",a)),True)[1]
mb.showinfo=lambda *a,**k:calls.append(("info",a)); mb.showwarning=lambda *a,**k:calls.append(("warn",a)); mb.showerror=lambda *a,**k:calls.append(("err",a))
fd.asksaveasfilename=lambda **k:None; fd.askopenfilename=lambda **k:None
fnt.nametofont=lambda n:FontObj()
tk.ttk=ttk; tk.messagebox=mb; tk.filedialog=fd; tk.font=fnt
sys.modules.update({"tkinter":tk,"tkinter.ttk":ttk,"tkinter.messagebox":mb,"tkinter.filedialog":fd,"tkinter.font":fnt})
import reminder_app as ra

tmp=Path(tempfile.mkdtemp())
ra.SETTINGS_FILE=tmp/"settings.json"; ra.IMPORT_LOG=tmp/"imp.log"
T=date(2026,11,24)
fails=0
def check(name,cond):
    global fails
    print(("PASS " if cond else "FAIL ")+name)
    if not cond: fails+=1

# ---------- core ----------
check("parse iso", ra.parse_date("2026-12-01",T)==date(2026,12,1))
check("parse dmy", ra.parse_date("01/12/2026",T)==date(2026,12,1))
check("parse tomorrow", ra.parse_date("Tomorrow",T)==T+timedelta(1))
for bad in ("","abc","31/02/2026","2026-13-01","01/01/1999","2026-1-1x"):
    try: ra.parse_date(bad,T); check("reject "+repr(bad),False)
    except ValueError: check("reject "+repr(bad),True)
for bad in ("", "   ", "x"*101):
    try: ra.validate_title(bad); check("title reject",False)
    except ValueError: check("title reject "+str(len(bad)),True)
check("category canonical", ra.validate_category("  work ")=="Work")
check("category custom", ra.validate_category("gym")=="Gym")
check("category empty->Other", ra.validate_category("")=="Other")
try: ra.validate_priority("urgent"); check("priority reject",False)
except ValueError: check("priority reject",True)
r=ra.Reminder(1,"t",T-timedelta(2)); check("overdue status",r.status(T)=="Overdue" and r.days_text(T)=="2 days late")
r2=ra.Reminder(2,"t",T); check("today",r2.status(T)=="Due today" and r2.days_text(T)=="Today")
r3=ra.Reminder(3,"t",T+timedelta(1)); check("tomorrow text",r3.days_text(T)=="Tomorrow")
r3.is_completed=True; check("completed",r3.status(T)=="Completed")

# store: sample load, save, corrupt, bad entries
shutil.copy("sample_reminders.json", tmp/"sample.json")
st=ra.ReminderStore(tmp/"data.json", tmp/"sample.json"); st.load()
check("sample loads 40", len(st.items)==40 and st.load_notes)
check("save ok", st.save() and (tmp/"data.json").exists())
st2=ra.ReminderStore(tmp/"data.json"); st2.load(); check("roundtrip", len(st2.items)==40)
(tmp/"data.json").write_text("{not json")
st3=ra.ReminderStore(tmp/"data.json"); st3.load()
check("corrupt -> empty + backup", st3.items==[] and any(p.name.startswith("data.corrupt-") for p in tmp.iterdir()))
(tmp/"d2.json").write_text(json.dumps([{"id":1,"title":"ok","due_date":"2026-12-01"},{"id":2,"title":"","due_date":"2026-12-01"},{"id":3,"title":"x","due_date":"bad"},{"id":1,"title":"dup id","due_date":"2026-12-02"}]))
st4=ra.ReminderStore(tmp/"d2.json"); st4.load()
check("skips invalid, fixes dup ids", len(st4.items)==2 and len({r.id for r in st4.items})==2 and st4.load_notes)
check("missing file ok", ra.ReminderStore(tmp/"none.json").load() is None)

items=st.items
s=ra.compute_summary(items,T)
check("summary totals", s["total"]==40 and s["overdue"]+s["due_today"]+s["upcoming"]+s["completed"]==40)
print("   summary:",{k:s[k] for k in("overdue","due_today","upcoming","completed","avg_days","completion_rate","high_overdue")})
check("empty summary", ra.compute_summary([],T)["total"]==0)
check("filter keyword", all("python" in r.title.lower() or "python" in r.category.lower() for r in ra.filter_reminders(items,"python")))
check("filter overdue", all(r.status(T)=="Overdue" for r in ra.filter_reminders(items,status="Overdue",today=T)))
check("filter active", all(not r.is_completed for r in ra.filter_reminders(items,status="Active",today=T)))
check("filter combo", all(r.category=="Finance" and r.priority=="High" for r in ra.filter_reminders(items,category="Finance",priority="High")))

# exports + import
ra.export_csv(items,tmp/"o.csv",T); ra.export_markdown(items,tmp/"o.md",T); ra.export_text(items,tmp/"o.txt",T)
check("exports written", all((tmp/f"o.{e}").stat().st_size>100 for e in("csv","md","txt")))
(tmp/"in.csv").write_text("Title,Due_Date,Category,Priority,Is_Completed\nNew task,2026-12-05,work,high,no\n,2026-12-05,,,\nBad date,32/13/2026,,,\nBad pri,2026-12-05,,urgent,\nNew task,2026-12-05,,,\nDone one,05/12/2026,Health,low,yes\n",encoding="utf-8")
new,errs,dupes=ra.import_csv(tmp/"in.csv",[],100)
check("import 2 ok, 3 errors, 1 dup", len(new)==2 and len(errs)==3 and dupes==1)
print("   errors:",errs)
check("import ids/values", new[0].id==100 and new[0].category=="Work" and new[1].is_completed)
(tmp/"nocols.csv").write_text("a,b\n1,2\n")
try: ra.import_csv(tmp/"nocols.csv",[],1); check("missing cols",False)
except ValueError: check("missing cols",True)
(tmp/"empty.csv").write_text("")
try: ra.import_csv(tmp/"empty.csv",[],1); check("empty csv",False)
except ValueError: check("empty csv",True)

# ---------- GUI flows via fake tk ----------
store=ra.ReminderStore(tmp/"gui.json", tmp/"sample.json")
app=ra.ReminderApp(W(), store)
check("gui init + rows", len(app.tree.rows)==40)
n=len(store.items)
app.title_var.set("Buy milk"); app.date_var.set("30/11/2026"); app.cat_var.set("personal"); app.pri_var.set("High")
app.submit()
check("add via form", len(store.items)==n+1 and store.items[-1].category=="Personal" and (tmp/"gui.json").exists())
new_id=store.items[-1].id
app.title_var.set(""); app.submit(); check("empty title shows error", app.form_error.get()!="" and len(store.items)==n+1)
app.title_var.set("x"); app.date_var.set("nonsense"); app.submit(); check("bad date shows error", "Invalid" in app.form_error.get())
app.tree.sel=[str(new_id)]; app.edit_selected()
check("edit loads form", app.editing_id==new_id and app.title_var.get()=="Buy milk")
app.title_var.set("Buy oat milk"); app.submit()
check("edit saved", store.get(new_id).title=="Buy oat milk" and app.editing_id is None)
app.tree.sel=[str(new_id)]; app.toggle_selected(); check("toggle done", store.get(new_id).is_completed)
app.toggle_selected(); check("toggle undone", not store.get(new_id).is_completed)
app.tree.sel=[str(new_id)]; app.delete_selected(); check("delete", store.get(new_id) is None and len(store.items)==n)
app.undo_delete(); check("undo", store.get(new_id) is not None and len(store.items)==n+1)
app.undo_delete(); check("undo empty ok", True)
app.quick_filter("Overdue"); check("quick filter", all(v[4]=="Overdue" for v in app.tree.rows.values()) and app.tree.rows)
app.clear_filters(); check("clear filters", len(app.tree.rows)==n+1)
app.search_var.set("zzzz"); check("no match", len(app.tree.rows)==0); app.clear_filters()
for k in ("id","title","due","when","status","priority","category"):
    app.sort_by(k); app.sort_by(k)
check("all sorts ok", True)
app.toggle_theme(); app.toggle_theme(); check("theme toggle", app.theme_name=="light" and json.loads(ra.SETTINGS_FILE.read_text())["theme"]=="light")
check("charts drew", app.status_canvas.items>0 and app.cat_canvas.items>0 and app.pri_canvas.items>0)
app.startup_alert(); check("startup alert", any(c[0]=="warn" for c in calls))
app.store.items=[]; app.refresh(); check("empty state renders", app.status_canvas.items==1)
app.flash("hi"); app.show_about(); app.show_shortcuts(); app.show_quick_help()

# ---------- v4: time / repeat / alarms / quick add ----------
from datetime import datetime
for raw,exp in (("17:30","17:30"),("5pm","17:00"),("5:30 pm","17:30"),("12am","00:00"),("12pm","12:00"),("9","09:00"),("",""),(" 07:05 ","07:05")):
    check(f"parse_time {raw!r}", ra.parse_time(raw)==exp)
for bad in ("25:00","12:60","13pm","0am","abc","5:5"):
    try: ra.parse_time(bad); check("parse_time reject "+bad,False)
    except ValueError: check("parse_time reject "+bad,True)
check("fmt_span", ra.fmt_span(7500)=="2h 05m" and ra.fmt_span(600)=="10 min" and ra.fmt_span(20)=="<1 min" and ra.fmt_span(3725,True)=="1h 02m 05s")
check("next daily", ra.next_occurrence(date(2026,12,31),"Daily")==date(2027,1,1))
check("next weekly", ra.next_occurrence(date(2026,11,24),"Weekly")==date(2026,12,1))
check("next monthly clamp", ra.next_occurrence(date(2026,1,31),"Monthly")==date(2026,2,28))
check("next monthly year roll", ra.next_occurrence(date(2026,12,15),"Monthly")==date(2027,1,15))
check("repeat validate", ra.validate_repeat("WEEKLY")=="Weekly" and ra.validate_repeat("")=="None")
rt=ra.Reminder(1,"x",date.today(),due_time="00:00"); check("timed passed -> Overdue", rt.status()=="Overdue" and rt.days_text().endswith("late"))
rt2=ra.Reminder(1,"x",date.today(),due_time="23:59")
if datetime.now().strftime("%H:%M")<"23:59": check("timed future -> Due today + countdown", rt2.status()=="Due today" and rt2.days_text().startswith("in "))
check("due_datetime", ra.Reminder(1,"x",T,due_time="17:05").due_datetime()==datetime(2026,11,24,17,5))
rd=ra.Reminder.from_dict(ra.Reminder(1,"x",T,due_time="09:00",repeat="Weekly").to_dict()); check("dict roundtrip time/repeat", rd.due_time=="09:00" and rd.repeat=="Weekly")
check("old json w/o time ok", ra.Reminder.from_dict({"id":1,"title":"a","due_date":"2026-12-01"}).repeat=="None")
# store.complete
cs=ra.ReminderStore(tmp/"c.json"); a=ra.Reminder(1,"Gym",T,repeat="Weekly",due_time="06:00"); cs.items=[a]
n1=cs.complete(a,T); check("repeat spawns next", a.is_completed and n1 and n1.due_date==date(2026,12,1) and n1.due_time=="06:00" and not n1.is_completed and n1.id==2)
b=ra.Reminder(3,"Gym",T,repeat="Weekly"); cs.items.append(b); check("no duplicate spawn", cs.complete(b,T) is None)
c=ra.Reminder(4,"Old",date(2026,10,1),repeat="Daily"); cs.items.append(c); n2=cs.complete(c,T); check("catch-up to today", n2.due_date==T)
d=ra.Reminder(5,"Once",T); cs.items.append(d); check("non-repeat no spawn", cs.complete(d,T) is None and d.is_completed)
# alarms
NOW=datetime(2026,11,24,14,0)
al=[ra.Reminder(1,"a",T,due_time="13:59"),ra.Reminder(2,"b",T,due_time="14:01"),ra.Reminder(3,"c",T),ra.Reminder(4,"d",T,due_time="10:00",is_completed=True),ra.Reminder(5,"e",T,due_time="13:00")]
fired={(5,T,"13:00")}
check("due_alarms picks only ripe", [r.id for r in ra.due_alarms(al,NOW,fired,{})]==[1])
check("snooze waits", ra.due_alarms(al,NOW,fired,{1:datetime(2026,11,24,14,5)})==[])
check("snooze rings after", [r.id for r in ra.due_alarms(al,datetime(2026,11,24,14,6),fired,{1:datetime(2026,11,24,14,5)})]==[1,2])
# quick add parser
def q(txt): return ra.parse_quick_add(txt,NOW)
x=q("Submit report tomorrow 5pm !high #work"); check("qa full", (x["title"],x["due"],x["time"],x["priority"],x["category"])==("Submit report",date(2026,11,25),"17:00","High","Work"))
x=q("Call mom in 2 hours"); check("qa in 2 hours", (x["title"],x["due"],x["time"])==("Call mom",date(2026,11,24),"16:00"))
x=q("Gym every day 6am"); check("qa repeat+time rolls to tomorrow", (x["title"],x["repeat"],x["time"],x["due"])==("Gym","Daily","06:00",date(2026,11,25)))
x=q("Team meeting friday 10:30"); check("qa weekday", (x["title"],x["due"],x["time"])==("Team meeting",date(2026,11,27),"10:30"))
x=q("Pay fees 05/12/2026 !high #finance"); check("qa dmy date", (x["title"],x["due"],x["priority"],x["category"])==("Pay fees",date(2026,12,5),"High","Finance"))
x=q("Rent monthly"); check("qa monthly", (x["title"],x["repeat"],x["due"])==("Rent","Monthly",T))
x=q("Buy milk"); check("qa plain", (x["title"],x["due"],x["time"])==("Buy milk",T,""))
x=q("Dentist on 2026-12-01 at 4:30pm"); check("qa iso + at", (x["title"],x["due"],x["time"])==("Dentist",date(2026,12,1),"16:30"))
x=q("Lunch with friend at 1pm"); check("qa past time -> tomorrow", (x["title"],x["due"],x["time"])==("Lunch with friend",date(2026,11,25),"13:00"))
x=q("Submit assignment in 3 days"); check("qa in 3 days", (x["title"],x["due"])==("Submit assignment",date(2026,11,27)))
x=q("Meet Sunita"); check("qa sun not matched in name", x["title"]=="Meet Sunita" and x["due"]==T)
x=q("Revise notes next monday !low"); check("qa next monday", (x["title"],x["due"],x["priority"])==("Revise notes",date(2026,11,30),"Low"))
x=q("   "); check("qa empty", x["title"]=="")
x=q("Pay bill 31/02/2026"); check("qa bad date does not crash", x["due"]==T)
# csv import with time/repeat
(tmp/"in2.csv").write_text("title,due_date,due_time,repeat\nStandup,2026-12-01,9am,daily\nBad time,2026-12-01,99:99,\n",encoding="utf-8")
n2,e2,_=ra.import_csv(tmp/"in2.csv",[],1); check("import time/repeat", len(n2)==1 and n2[0].due_time=="09:00" and n2[0].repeat=="Daily" and len(e2)==1)
ra.export_csv(n2,tmp/"o2.csv",T); check("csv export has time/repeat", "due_time,repeat" in (tmp/"o2.csv").read_text())
ra.export_markdown(n2,tmp/"o2.md",T); ra.export_text(n2,tmp/"o2.txt",T); check("md/txt export with time", "2026-12-01 09:00" in (tmp/"o2.md").read_text() and "2026-12-01 09:00" in (tmp/"o2.txt").read_text())

# ---------- v4 GUI flows ----------
store=ra.ReminderStore(tmp/"gui2.json", tmp/"sample.json")
app=ra.ReminderApp(W(), store); base=len(store.items)
app.quick_var.set("Write report tomorrow 5pm !high #work every week"); app._update_quick_preview()
check("quick preview text", app.quick_preview.get().startswith("Will add:") and "17:00" in app.quick_preview.get())
app.quick_add(); r=store.items[-1]
check("quick add creates", len(store.items)==base+1 and r.title=="Write report" and r.due_time=="17:00" and r.repeat=="Weekly" and r.priority=="High" and app.quick_var.get()=="")
app.quick_var.set("   "); app.quick_add(); check("quick add blank ignored", len(store.items)==base+1)
app.quick_var.set("!high #work"); app.quick_add(); check("quick add no title rejected", len(store.items)==base+1 and "empty" in app.quick_preview.get().lower())
app.title_var.set("Form timed"); app.date_var.set("today"); app.time_var.set("11:59pm"); app.repeat_var.set("Daily"); app.submit()
f=store.items[-1]; check("form time+repeat", f.title=="Form timed" and f.due_time=="23:59" and f.repeat=="Daily")
app.title_var.set("x"); app.date_var.set("today"); app.time_var.set("99:99"); app.submit(); check("form bad time rejected", "time" in app.form_error.get().lower())
app.clear_form()
app.tree.sel=[str(f.id)]; app.set_completed([f.id],True)
check("done spawns repeat", any(r.title=="Form timed" and not r.is_completed and r.due_date>f.due_date or (r.title=="Form timed" and not r.is_completed and r.id!=f.id) for r in store.items))
n_before=len(store.items); app.tree.sel=[str(r.id)]; old=(r.due_date,r.due_time); app.snooze_selected(); check("snooze selected moves +1h", (r.due_date,r.due_time)!=old)
# live tick: alarm fires for ripe timed reminder, only once
ripe=ra.Reminder(store.next_id(),"RING NOW",date.today(),due_time="00:00"); store.add(ripe)
shown=[]; app.show_alarm=lambda rem: shown.append(rem.id)
app._live_tick(); check("tick fires alarm", shown==[ripe.id] and (ripe.id,ripe.due_date,"00:00") in app.fired)
app._live_tick(); check("alarm fires once", shown==[ripe.id])
app.snoozed[ripe.id]=datetime.now()-timedelta(seconds=1); app._live_tick(); check("snooze re-rings", shown==[ripe.id,ripe.id] and ripe.id not in app.snoozed)
check("tick updates clock/next", app.clock_var.get()!="" and app.next_var.get().startswith("Next up"))
# status flip detected by tick -> refresh
rows_before=app._row_state.copy(); ripe.is_completed=True; app._live_tick(); check("tick detects status change", app._row_state[ripe.id]=="Completed")
# real show_alarm path with fake widgets does not crash
ra.ReminderApp.show_alarm(app, ra.Reminder(99,"alarm window",date.today(),due_time="10:00")); check("show_alarm builds", len(app.alarm_windows)==1)
# animation helpers (after() is a no-op in the fake, so call the frames directly)
app._set_stat("total", 5); app._animate_progress(60.0); app._draw_all_charts(0.5); app._draw_all_charts(1.0)
check("charts partial/full draw", app.status_canvas.items>0 and app.cat_canvas.items>0)
app.refresh_summary(force_animate=True); app.toggle_theme(); app.toggle_theme()
check("next_text variants", app._next_text(datetime.now()).startswith("Next up"))
nb=len(app.store.items); app.add_demo_alarm(); dm=app.store.items[-1]
check("demo alarm created & will ring", len(app.store.items)==nb+1 and dm.due_time and (dm.id,dm.due_date,dm.due_time) not in app.fired and dm.due_datetime()>datetime.now()-timedelta(seconds=1))
app.store.items=[]; app.refresh(); check("empty next text", "nothing pending" in app._next_text(datetime.now()))

print("\nFAILS:",fails); sys.exit(1 if fails else 0)
