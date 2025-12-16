import streamlit as st
import google.generativeai as genai
import json
import io
from pypdf import PdfReader
from docx import Document

# ==========================================
# 1. SETUP & SECURITY
# ==========================================
st.set_page_config(page_title="GenAI MBD Architect", layout="wide", page_icon="⚙️")

# Securely fetch API Key from Streamlit Secrets
api_key = None
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

if not api_key:
    st.warning("⚠️ API Key missing. Please add `GOOGLE_API_KEY` to your Streamlit Secrets.")
    st.stop()

genai.configure(api_key=api_key)

# ==========================================
# 2. FILE READING UTILITIES (New Feature)
# ==========================================
def read_file_content(uploaded_file):
    """Extracts text from PDF, DOCX, or TXT/C/CPP files."""
    try:
        file_ext = uploaded_file.name.split('.')[-1].lower()
        
        if file_ext == 'pdf':
            reader = PdfReader(uploaded_file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
            
        elif file_ext in ['docx', 'doc']:
            doc = Document(uploaded_file)
            text = "\n".join([para.text for para in doc.paragraphs])
            return text
            
        else:
            # Assume text based (c, cpp, h, txt, md)
            return uploaded_file.getvalue().decode("utf-8")
            
    except Exception as e:
        return f"Error reading file {uploaded_file.name}: {str(e)}"

# ==========================================
# 3. PARSERS (The "Translator" Logic)
# ==========================================
def json_to_mermaid(data):
    mermaid_lines = ["graph LR"]
    for comp in data.get('components', []):
        name = comp['name']
        ctype = comp['type']
        if ctype == "Subsystem":
            line = f"    {name}(({name}<br/>Subsystem))"
        elif ctype == "ModelReference":
            line = f"    {name}[[{name}<br/>ModelRef]]"
        elif ctype == "StateflowChart":
            line = f"    {name}{{ {name}<br/>Stateflow }}"
        elif ctype == "Inport":
            line = f"    {name}([{name} >])"
        elif ctype == "Outport":
            line = f"    {name}(([> {name}]))"
        else:
            line = f"    {name}[{name}]"
        mermaid_lines.append(line)

    for conn in data.get('connections', []):
        src = conn['source'].split('/')[0] 
        dst = conn['destination'].split('/')[0]
        mermaid_lines.append(f"    {src} --> {dst}")
    return "\n".join(mermaid_lines)

def json_to_matlab(data):
    model_name = data.get('system_name', 'GenAI_Model').replace(" ", "_")
    lines = []
    lines.append(f"% Auto-Generated MBD Build Script for: {model_name}")
    lines.append("bdclose all; clear; clc;")
    lines.append(f"new_system('{model_name}');")
    lines.append(f"open_system('{model_name}');")
    
    lib_map = {
        "Gain": "simulink/Math Operations/Gain",
        "Sum": "simulink/Math Operations/Add",
        "Integrator": "simulink/Continuous/Integrator",
        "Inport": "simulink/Sources/In1",
        "Outport": "simulink/Sinks/Out1",
        "Subsystem": "built-in/Subsystem",
        "ModelReference": "simulink/Ports & Subsystems/Model",
        "StateflowChart": "sflib/Chart",
        "Constant": "simulink/Sources/Constant",
        "Scope": "simulink/Sinks/Scope"
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
# 4. AI ENGINE (The Brain)
# ==========================================
SYSTEM_PROMPT = """
You are a Senior MBD Architect. 
Your task: Analyze the input (C/C++ Code OR Requirements Text) and design a valid Simulink/Stateflow architecture.
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
        # FIX: Switched to 'gemini-1.5-flash' which is widely available on free tier
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        full_prompt = SYSTEM_PROMPT + "\n\nUSER INPUT DATA:\n" + user_input
        response = model.generate_content(full_prompt)
        
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        # Fallback debug info
        st.error(f"AI Error: {str(e)}")
        return None

# ==========================================
# 5. FRONTEND UI
# ==========================================
st.title("🚀 GenAI MBD Architect")

tab1, tab2 = st.tabs(["✨ AI Generator", "📂 Re-Use / Viewer"])

with tab1:
    st.info("Upload inputs to generate architecture.")
    
    # FIX: Combined inputs into one cleaner interface
    input_method = st.radio("Select Input Source:", ["Upload C/C++ Code", "Upload Requirements (PDF/Docx/Txt)"])
    
    user_data = ""
    
    if input_method == "Upload C/C++ Code":
        files = st.file_uploader("Upload .c, .cpp, .h files", accept_multiple_files=True)
        if files:
            for f in files:
                text = read_file_content(f)
                user_data += f"\n// FILE: {f.name}\n" + text
            st.success(f"Loaded {len(files)} code files.")
            
    else:
        # FIX: Changed from Text Area to File Uploader
        req_files = st.file_uploader("Upload Requirements", type=['pdf', 'docx', 'txt', 'md'], accept_multiple_files=True)
        if req_files:
            for f in req_files:
                text = read_file_content(f)
                user_data += f"\n--- REQUIREMENT DOC: {f.name} ---\n" + text
            st.success(f"Loaded {len(req_files)} requirement documents.")

    if st.button("Generate Architecture ⚡"):
        if not user_data:
            st.error("Please provide input data first!")
        else:
            with st.spinner("AI is architecting the solution... (Using gemini-1.5-flash)"):
                json_result = get_ai_response(user_data)
                
                if json_result:
                    mermaid_code = json_to_mermaid(json_result)
                    matlab_code = json_to_matlab(json_result)
                    json_str = json.dumps(json_result, indent=2)
                    
                    st.success("Architecture Designed Successfully!")
                    st.subheader("1. Visual Architecture")
                    st.markdown(f"```mermaid\n{mermaid_code}\n```")
                    
                    st.subheader("2. Export Artifacts")
                    c1, c2, c3 = st.columns(3)
                    c1.download_button("📥 Download JSON", json_str, "mbd_model.json", "application/json")
                    c2.download_button("📥 Download .m Script", matlab_code, "build_model.m", "text/plain")
                    c3.download_button("📥 Download Diagram", mermaid_code, "diagram.mmd", "text/plain")

with tab2:
    st.info("Viewer Mode: No AI required.")
    uploaded_json = st.file_uploader("Upload .json Model File", type=["json"])
    if uploaded_json:
        try:
            data = json.load(uploaded_json)
            m_code = json_to_mermaid(data)
            mat_code = json_to_matlab(data)
            st.success("Model Loaded!")
            st.markdown(f"```mermaid\n{m_code}\n```")
        except Exception as e:
            st.error(f"Invalid JSON: {e}")
