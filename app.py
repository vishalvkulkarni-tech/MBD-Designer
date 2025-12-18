import streamlit as st
import google.generativeai as genai
import json
import base64
import re
from pypdf import PdfReader
from docx import Document

# ==========================================
# 1. SETUP & SECURITY
# ==========================================
st.set_page_config(page_title="GenAI MBD Architect", layout="wide", page_icon="⚙️")

# Fetch API Key
api_key = st.secrets.get("GOOGLE_API_KEY")
if not api_key:
    api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

if not api_key:
    st.error("⚠️ API Key missing. Please add `GOOGLE_API_KEY` to Streamlit Secrets.")
    st.stop()

genai.configure(api_key=api_key)

# ==========================================
# 2. DYNAMIC MODEL SELECTOR
# ==========================================
def get_working_model():
    """
    Queries Google API for a list of available models and returns the first one
    that supports content generation. This prevents 404 errors.
    """
    try:
        models = list(genai.list_models())
        priority_keywords = ['flash', 'pro', 'gemini']
        generation_models = [m for m in models if 'generateContent' in m.supported_generation_methods]
        
        if not generation_models:
            return None

        for keyword in priority_keywords:
            for m in generation_models:
                if keyword in m.name:
                    return m.name
        return generation_models[0].name

    except Exception as e:
        return 'models/gemini-pro'

# Initialize Model on App Start
if 'active_model' not in st.session_state:
    with st.spinner("Connecting to Google AI..."):
        model_name = get_working_model()
        if model_name:
            st.session_state['active_model'] = model_name
        else:
            st.error("❌ Critical Error: No available models found for this API Key.")
            st.stop()

st.sidebar.success(f"✅ Connected to: {st.session_state['active_model']}")

# ==========================================
# 3. HELPER: MERMAID IMAGE RENDERER
# ==========================================
def render_mermaid_ui(mermaid_code):
    """
    Renders diagram as a static image via mermaid.ink.
    """
    try:
        graphbytes = mermaid_code.encode("utf8")
        base64_bytes = base64.b64encode(graphbytes)
        base64_string = base64_bytes.decode("ascii")
        url = "https://mermaid.ink/img/" + base64_string
        st.image(url, caption="System Architecture", use_container_width=True)
    except Exception:
        st.warning("Could not render visual diagram. Please view the code below.")
    
    with st.expander("🔍 View Diagram Code (Debug)"):
        st.code(mermaid_code, language='mermaid')

# ==========================================
# 4. FILE READERS
# ==========================================
def read_file_content(uploaded_file):
    try:
        file_ext = uploaded_file.name.split('.')[-1].lower()
        if file_ext == 'pdf':
            reader = PdfReader(uploaded_file)
            return "\n".join([page.extract_text() for page in reader.pages])
        elif file_ext in ['docx', 'doc']:
            doc = Document(uploaded_file)
            return "\n".join([para.text for para in doc.paragraphs])
        else:
            return uploaded_file.getvalue().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"Error reading {uploaded_file.name}: {e}"

# ==========================================
# 5. PARSERS (MATLAB & MERMAID)
# ==========================================
def sanitize_id(text):
    """
    CRITICAL FIX: 
    1. Removes special chars.
    2. Adds 'id_' prefix to ensure it never starts with a number or matches a keyword like 'End'.
    """
    clean_text = re.sub(r'[^a-zA-Z0-9]', '', text)
    return f"id_{clean_text}"

def sanitize_label(text):
    """Escapes double quotes to prevent breaking the Mermaid string."""
    return text.replace('"', "'")

def json_to_mermaid(data):
    mermaid_lines = ["graph LR"]
    
    # Nodes
    for comp in data.get('components', []):
        raw_name = comp['name']
        safe_id = sanitize_id(raw_name)  # Unique ID
        label = sanitize_label(raw_name) # Human readable label
        ctype = comp['type']
        
        # Format: SafeID["Readable Name"]
        if ctype == "Subsystem":
            mermaid_lines.append(f'    {safe_id}(("{label}<br/>Subsystem"))')
        elif ctype == "ModelReference":
            mermaid_lines.append(f'    {safe_id}[["{label}<br/>ModelRef"]]')
        elif ctype == "StateflowChart":
            mermaid_lines.append(f'    {safe_id}{{ "{label}<br/>Stateflow" }}')
        elif ctype == "Inport":
            mermaid_lines.append(f'    {safe_id}(["{label} >"])')
        elif ctype == "Outport":
            mermaid_lines.append(f'    {safe_id}((["> {label}"]))')
        else:
            mermaid_lines.append(f'    {safe_id}["{label}"]')

    # Connections
    for conn in data.get('connections', []):
        # Handle "Block/Port" format by splitting
        src_raw = conn['source'].split('/')[0]
        dst_raw = conn['destination'].split('/')[0]
        
        src_safe = sanitize_id(src_raw)
        dst_safe = sanitize_id(dst_raw)
        
        mermaid_lines.append(f"    {src_safe} --> {dst_safe}")

    return "\n".join(mermaid_lines)

def json_to_matlab(data):
    model_name = data.get('system_name', 'GenAI_Model').replace(" ", "_")
    lines = [f"% Auto-Generated MBD Build Script for: {model_name}", "bdclose all; clear; clc;", f"new_system('{model_name}');", f"open_system('{model_name}');"]
    
    lib_map = {
        "Gain": "simulink/Math Operations/Gain", "Sum": "simulink/Math Operations/Add",
        "Integrator": "simulink/Continuous/Integrator", "Inport": "simulink/Sources/In1",
        "Outport": "simulink/Sinks/Out1", "Subsystem": "built-in/Subsystem",
        "ModelReference": "simulink/Ports & Subsystems/Model", "StateflowChart": "sflib/Chart",
        "Constant": "simulink/Sources/Constant", "Scope": "simulink/Sinks/Scope"
    }

    for comp in data.get('components', []):
        blk_type = comp['type']
        blk_name = comp['name'].replace(" ", "_")
        lib_path = lib_map.get(blk_type, "built-in/Subsystem")
        lines.append(f"add_block('{lib_path}', '{model_name}/{blk_name}');")
        if 'parameters' in comp:
            for k, v in comp['parameters'].items():
                lines.append(f"set_param('{model_name}/{blk_name}', '{k}', '{v}');")
        if 'position' in comp:
            pos = str(comp['position']).replace('[', '').replace(']', '')
            lines.append(f"set_param('{model_name}/{blk_name}', 'Position', [{pos}]);")

    lines.append("% Connecting Blocks...")
    for conn in data.get('connections', []):
        src = conn['source'].replace(" ", "_")
        dst = conn['destination'].replace(" ", "_")
        lines.append(f"try add_line('{model_name}', '{src}', '{dst}', 'autorouting', 'on'); catch; end")

    lines.append("save_system;")
    return "\n".join(lines)

# ==========================================
# 6. AI ENGINE
# ==========================================
SYSTEM_PROMPT = """
You are a Senior MBD Architect. 
Your task: Analyze the input (Code/Requirements) and design a valid Simulink/Stateflow architecture.
OUTPUT FORMAT: ONLY output a valid JSON object. No markdown.
JSON SCHEMA:
{
  "system_name": "String (No Spaces)",
  "components": [
    { "name": "String", "type": "String (Inport|Outport|Gain|Sum|Integrator|Subsystem|StateflowChart|ModelReference|Constant|Scope)", "parameters": { "Key": "Value" }, "position": [left, top, right, bottom] }
  ],
  "connections": [ { "source": "BlockName/1", "destination": "BlockName/1" } ]
}
"""

def get_ai_response(user_input):
    try:
        model_name = st.session_state['active_model']
        model = genai.GenerativeModel(model_name)
        full_prompt = SYSTEM_PROMPT + "\n\nUSER INPUT DATA:\n" + user_input
        response = model.generate_content(full_prompt)
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"AI Error: {str(e)}")
        return None

# ==========================================
# 7. FRONTEND UI
# ==========================================
st.title("🚀 GenAI MBD Architect")
st.markdown("Convert **Requirements** (PDF/Doc) or **Legacy Code** (C/C++) into Simulink Models.")

tab1, tab2 = st.tabs(["✨ AI Generator", "📂 Viewer Mode"])

with tab1:
    uploaded_files = st.file_uploader("Upload Files (Code or Docs)", type=['c', 'cpp', 'h', 'txt', 'pdf', 'docx', 'md'], accept_multiple_files=True)
    
    if st.button("Generate Architecture ⚡"):
        if not uploaded_files:
            st.error("Please upload files first!")
        else:
            user_data = ""
            progress_bar = st.progress(0)
            
            for i, f in enumerate(uploaded_files):
                text = read_file_content(f)
                user_data += f"\n// FILE: {f.name}\n{text}\n"
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            with st.spinner(f"Architecting with {st.session_state['active_model']}..."):
                json_result = get_ai_response(user_data)
                
                if json_result:
                    mermaid_code = json_to_mermaid(json_result)
                    matlab_code = json_to_matlab(json_result)
                    json_str = json.dumps(json_result, indent=2)
                    
                    st.success("Success!")
                    
                    st.subheader("1. Visual Architecture")
                    render_mermaid_ui(mermaid_code)
                    
                    st.subheader("2. Export Artifacts")
                    c1, c2, c3 = st.columns(3)
                    c1.download_button("📥 Download JSON", json_str, "mbd_model.json", "application/json")
                    c2.download_button("📥 Download .m Script", matlab_code, "build_model.m", "text/plain")
                    c3.download_button("📥 Download Diagram", mermaid_code, "diagram.mmd", "text/plain")

with tab2:
    uploaded_json = st.file_uploader("Upload .json Model", type=["json"])
    if uploaded_json:
        try:
            data = json.load(uploaded_json)
            m_code = json_to_mermaid(data)
            mat_code = json_to_matlab(data)
            
            render_mermaid_ui(m_code)
            
            st.download_button("📥 Download .m Script", mat_code, "build_model.m", "text/plain")
        except Exception as e:
            st.error(f"Invalid JSON: {e}")
