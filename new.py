import streamlit as st
import pyrebase
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import math
from streamlit_autorefresh import st_autorefresh
import numpy as np

st.set_page_config(page_title="MTE Live Dashboard", layout="wide")

firebaseConfig = {
    'apiKey': "AIzaSyAzXYx4LsVfV7I5E7tL35rVUdzlFGQqLKU",
    'authDomain': "mte-website-best.firebaseapp.com",
    'databaseURL': "https://mte-website-best-default-rtdb.asia-southeast1.firebasedatabase.app",
    'projectId': "mte-website-best",
    'storageBucket': "mte-website-best.appspot.com",
    'messagingSenderId': "680810824940",
    'appId': "1:680810824940:web:70f8311fda11c3981211c9",
    'measurementId': "G-XYEN19L1EL"
}

firebase = pyrebase.initialize_app(firebaseConfig)
auth = firebase.auth()
db = firebase.database()

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_email" not in st.session_state: st.session_state.user_email = ""
if "user_data" not in st.session_state: st.session_state.user_data = None
if "force_refresh_toggle" not in st.session_state: st.session_state.force_refresh_toggle = False
if "recording" not in st.session_state: st.session_state.recording = False
if "record_start_time" not in st.session_state: st.session_state.record_start_time = None

def cleanemail(email: str) -> str:
    return email.replace("@","_").replace(".","_") if email else ""

def to_ist(dt: datetime) -> datetime:
    return dt + timedelta(hours=5, minutes=30) if dt else None

def _normalize_record(rec: dict) -> dict:
    out = dict(rec) if isinstance(rec, dict) else {}
    if "Timestamp" not in out:
        for k in list(out.keys()):
            if k.lower() in ("timestamp","time","ts","date","datetime"):
                out["Timestamp"] = out.pop(k)
                break
    if "Timestamp" in out:
        val = out["Timestamp"]
        try:
            if isinstance(val,(int,float)):
                out["Timestamp"] = datetime.utcfromtimestamp(val/1000).isoformat() if val>1e10 else datetime.utcfromtimestamp(val).isoformat()
            else:
                out["Timestamp"] = str(val)
        except: out["Timestamp"] = str(val)
    for axis in ("x","y","angle"):
        if axis in out:
            try: out[axis] = float(out[axis])
            except: out.pop(axis,None)
    return out

def get_last_1000(email: str) -> pd.DataFrame:
    if not email: return pd.DataFrame()
    cleaned_email = cleanemail(email)
    try:
        query = db.child("users").child(cleaned_email).child("sensor_data").order_by_key().limit_to_last(1000).get()
    except: return pd.DataFrame()
    items = [_normalize_record(d.val()) for d in query.each()] if query.each() else []
    return pd.DataFrame(items) if items else pd.DataFrame()

def monotonic_chain(points):
    pts = sorted(set(points))
    if len(pts)<=1: return pts
    def cross(o,a,b): return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower=[]
    for p in pts:
        while len(lower)>=2 and cross(lower[-2],lower[-1],p)<=0: lower.pop()
        lower.append(p)
    upper=[]
    for p in reversed(pts):
        while len(upper)>=2 and cross(upper[-2],upper[-1],p)<=0: upper.pop()
        upper.append(p)
    return lower[:-1]+upper[:-1]

def simplify_by_angle(polygon, angle_threshold_deg=10):
    if not polygon: return polygon
    pts=list(polygon)
    if len(pts)<3: return pts
    def angle(a,b,c):
        ab=(b[0]-a[0],b[1]-a[1])
        bc=(c[0]-b[0],c[1]-b[1])
        na=math.hypot(*ab); nb=math.hypot(*bc)
        if na==0 or nb==0: return 0
        dot=(ab[0]*bc[0]+ab[1]*bc[1])/(na*nb)
        dot=max(-1.0,min(1.0,dot))
        return math.degrees(math.acos(dot))
    out=[pts[0]]
    for i in range(1,len(pts)-1):
        a,b,c=pts[i-1],pts[i],pts[i+1]
        ang=angle(a,b,c)
        if abs(180-ang)>angle_threshold_deg: out.append(b)
    out.append(pts[-1])
    return out

def detect_shape(points):
    if len(points)<2: return "Unknown"
    xs, ys = zip(*points)
    x_range = max(xs)-min(xs)
    y_range = max(ys)-min(ys)
    if len(points)<=3: return "Line" if x_range>y_range*2 or y_range>x_range*2 else "Triangle"
    ratio = max(x_range, y_range)/min(x_range, y_range+1e-6)
    if ratio>5: return "Line"
    area = (max(xs)-min(xs))*(max(ys)-min(ys))
    perimeter = sum([math.hypot(xs[i]-xs[i-1], ys[i]-ys[i-1]) for i in range(1,len(xs))])
    if abs(area-(perimeter/4)**2)/area < 0.5: return "Square/Rectangle"
    cx, cy = np.mean(xs), np.mean(ys)
    r = np.mean([math.hypot(x-cx,y-cy) for x,y in points])
    if all(abs(math.hypot(x-cx,y-cy)-r)/r < 0.3 for x,y in points): return "Circle"
    return "Polygon"

def signup():
    st.header("Sign Up")
    email = st.text_input("Email", key="signup_email").strip()
    password = st.text_input("Password", type="password", key="signup_pass").strip()
    if st.button("Sign Up"):
        try:
            auth.create_user_with_email_and_password(email,password)
            db.child("users").child(cleanemail(email)).child("profile").set({"username": email})
            st.success("Account created. Log in now.")
        except Exception as e: st.error(f"Signup error: {e}")

def login():
    st.header("Login")
    email = st.text_input("Email", key="login_email").strip()
    password = st.text_input("Password", type="password", key="login_pass").strip()
    if st.button("Login"):
        try:
            user = auth.sign_in_with_email_and_password(email,password)
            st.session_state.logged_in=True
            st.session_state.user_email=email
            st.session_state.user_data=user
            st.success("Login successful.")
        except Exception as e: st.error(f"Login error: {e}")

def user_page():
    user_email=st.session_state.user_email
    username=cleanemail(user_email)
    st.sidebar.markdown("<h2 style='color:#5BC0DE;'>MTE Live Dashboard</h2>", unsafe_allow_html=True)
    st.sidebar.markdown(f"<b>User:</b> {username}", unsafe_allow_html=True)
    page=st.sidebar.radio("Navigation", ["Home","Live Contour","Stored Contours","Classes","Logout"])
    st.markdown("<style> body { background-color:#0B0C10;color:#C5C6C7; } .stButton>button {background-color:#45A29E;color:white;border-radius:8px;font-weight:bold;}</style>", unsafe_allow_html=True)

    if page=="Home":
        st.title(f"Welcome, {user_email}")
        st.write("Live contour detection — displays outer edge of recent points.")

    elif page=="Logout":
        if st.button("Logout"):
            st.session_state.logged_in=False
            st.session_state.user_email=""
            st.session_state.user_data=None
            st.success("Logged out.")

    elif page=="Live Contour":
        st.title("Live Ultrasonic Points → Outer Edge Contour (Open Line)")
        col1,col2=st.columns(2)
        with col1:
            if st.button("Record"):
                st.session_state.recording=True
                st.session_state.record_start_time=datetime.utcnow()
                st.success("Recording started.")
        with col2:
            if st.button("Stop"):
                st.session_state.recording=False
                st.info("Recording stopped.")

        st_autorefresh(interval=3000,key=f"live_contour_refresh_{st.session_state.force_refresh_toggle}")

        angle_tol = st.slider("Vertex angle tolerance (deg)", 5, 40, 10)
        max_points = st.slider("Max points to display", 5, 50, 20)

        df=get_last_1000(user_email)
        if df.empty: st.info("No sensor data yet."); return
        df["Timestamp"]=pd.to_datetime(df["Timestamp"],errors="coerce")
        df=df.dropna(subset=["Timestamp"]).sort_values("Timestamp")
        df["x"]=pd.to_numeric(df["x"],errors="coerce")
        df["y"]=pd.to_numeric(df["y"],errors="coerce")
        df=df.dropna(subset=["x","y"])
        if df.empty: st.info("No valid points."); return

        # Convert x,y to positive
        df["x"] = df["x"].abs()
        df["y"] = df["y"].abs()

        if st.session_state.recording:
            recent=df[df["Timestamp"]>=st.session_state.record_start_time].sort_values("Timestamp").tail(max_points)
        else:
            st.info("Press 'Record' to start recording points.")
            return
        if recent.empty: st.info("No points recorded yet."); return

        points=list(zip(recent['x'],recent['y']))
        hull=monotonic_chain(points)
        hull_simp=simplify_by_angle(hull,angle_threshold_deg=angle_tol)
        poly_x=[p[0] for p in hull_simp]; poly_y=[p[1] for p in hull_simp]

        shape=detect_shape(hull_simp)
        st.subheader(f"Detected Shape: {shape}")

        if st.button("Store Contour"):
            store_data=[{"x":p[0],"y":p[1]} for p in hull_simp]
            db.child("users").child(cleanemail(user_email)).child("stored_contours").push({
                "points": store_data,
                "shape": shape,
                "timestamp": datetime.utcnow().isoformat()
            })
            st.success("Contour stored successfully.")

        fig=go.Figure()
        fig.add_trace(go.Scatter(x=recent['x'],y=recent['y'],mode='markers',name='Points',marker=dict(size=6,color='cyan')))
        fig.add_trace(go.Scatter(x=poly_x,y=poly_y,mode='lines+markers',name='Outer Edge',line=dict(color='magenta',width=2),marker=dict(size=4)))
        fig.update_layout(title=f"Live Outer Edge Contour (last {len(recent)} points)",template="plotly_dark",height=520)
        st.plotly_chart(fig,use_container_width=True)

        display_df=recent.copy()
        display_df["Timestamp_IST"]=display_df["Timestamp"].apply(lambda t: to_ist(t).isoformat() if t else "")
        cols=[c for c in ["Timestamp_IST","x","y","angle"] if c in display_df.columns]
        st.dataframe(display_df[cols].reset_index(drop=True))

    elif page=="Stored Contours":
        st.title("Stored Contours")
        user_key=cleanemail(user_email)
        contours=db.child("users").child(user_key).child("stored_contours").get()
        if not contours.each():
            st.info("No stored contours.")
        else:
            for c in contours.each():
                st.subheader(f"Contour: {c.key()}")
                shape=c.val().get("shape","Unknown")
                st.write(f"Shape: {shape}")
                points=pd.DataFrame(c.val()["points"])
                points["x"] = points["x"].abs()
                points["y"] = points["y"].abs()
                fig=go.Figure()
                fig.add_trace(go.Scatter(x=points['x'],y=points['y'],mode='lines+markers',name='Contour',line=dict(color='orange',width=2),marker=dict(size=5)))
                fig.update_layout(title=f"Stored Contour ({shape})",template="plotly_dark",height=400)
                st.plotly_chart(fig,use_container_width=True)

    elif page=="Classes":
        st.title("Manage Classes")
        user_key=cleanemail(user_email)
        classes=db.child("users").child(user_key).child("classes").get()
        class_list=[c.key() for c in classes.each()] if classes.each() else []
        st.write("Existing Classes:", class_list)
        new_class=st.text_input("Add new class")
        if st.button("Add Class"):
            if new_class.strip():
                db.child("users").child(user_key).child("classes").child(new_class.strip()).set({"created": datetime.utcnow().isoformat()})
                st.success(f"Class '{new_class.strip()}' added.")
        del_class=st.selectbox("Delete class", [""]+class_list)
        if del_class and st.button("Delete Class"):
            db.child("users").child(user_key).child("classes").child(del_class).remove()
            st.warning(f"Class '{del_class}' deleted.")

st.title("MTE Project Dashboard — Live Open Edge Mode")
if st.session_state.logged_in: user_page()
else:
    auth_choice=st.selectbox("Select Action", ["Login","Sign Up"])
    if auth_choice=="Sign Up": signup()
    else: login()
