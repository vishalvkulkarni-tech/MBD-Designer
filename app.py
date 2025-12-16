import streamlit as st
import google.generativeai as genai
import json

# ==========================================
# 1. SETUP & SECURITY
# ==========================================
st.set_page_config(page_title="GenAI MBD Architect", layout="wide", page_icon="⚙️")

# Securely fetch API Key from Streamlit Secrets (Best Practice for Online)
api_key = None

if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    # Fallback: Allow manual entry if secrets aren't set up yet
    api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

if not api_key:
    st.warning("⚠️ API Key missing. Please add `GOOGLE_API_KEY` to your Streamlit Secrets.")
    st.stop()

# Configure the AI
genai.configure(api_key=api_key)

# ==========================================
# 2. PARSERS (The "Translator" Logic)
# ==========================================

def json_to_mermaid(data):
    """Converts JSON Architecture to Mermaid.js Diagram for Web View"""
    mermaid_lines = ["graph LR"]
    
    # 1. Create Nodes
    for comp in data.get('components', []):
        name = comp['name']
        ctype = comp['type']
        
        # Styling based on MBD Type
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

    # 2. Create Connections
    for conn in data.get('connections', []):
        src = conn['source'].split('/')[0] 
        dst = conn['destination'].split('/')[0]
        mermaid_lines.append(f"    {src} --> {dst}")

    return "\n".join(mermaid_lines)

def json_to_matlab(data):
    """Converts JSON Architecture to Executable MATLAB Build Script"""
    model_name = data.get('system_name', 'GenAI_Model')
    # Sanitize name (remove spaces for MATLAB compatibility)
    model_name = model_name.replace(" ", "_")
    
    lines = []
    lines.append(f"% Auto-Generated MBD Build Script for: {model_name}")
    lines.append("bdclose all; clear; clc;")
    lines.append(f"new_system('{model_name}');")
    lines.append(f"open_system('{model_name}');")
    
    # Mapping Standard JSON types to Real Simulink Library Paths
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

    # 1. Add Blocks
    for comp in data.get('components', []):
        blk_type = comp['type']
        blk_name = comp['name'].replace(" ", "_") # Sanitize block names
        
        lib_path = lib_map.get(blk_type, "built-in/Subsystem")
        
        lines.append(f"add_block('{lib_path}', '{model_name}/{blk_name}');")
        
        # Set Parameters
        if 'parameters' in comp:
            for k, v in comp['parameters'].items():
                lines.append(f"set_param('{model_name}/{blk_name}', '{k}', '{v}');")
        
        # Set Position
        if 'position' in comp:
            pos = str(comp['position']).replace('[', '').replace(']', '')
            lines.append(f"set_param('{model_name}/{blk_name}', 'Position', [{pos}]);")

    # 2. Add Lines (Wrapped in try-catch to prevent script failure on bad routes)
    lines.append("% Connecting Blocks...")
    for conn in data.get('connections', []):
        # Sanitize port names
        src = conn['source'].replace(" ", "_")
        dst = conn['destination'].replace(" ", "_")
        lines.append(f"try add_line('{model_name}', '{src}', '{dst}', 'autorouting', 'on'); catch; end")

    lines.append("save_system;")
    return "\n".join(lines)

# ==========================================
# 3. AI ENGINE (The Brain)
# ==========================================

SYSTEM_PROMPT = """
You are a Senior Model-Based Design (MBD) Architect. 
Your task: Analyze the input (C/C++ Code OR Requirements Text) and design a valid Simulink/Stateflow architecture.

OUTPUT FORMAT:
You must ONLY output a valid JSON object. No markdown formatting.

JSON SCHEMA:
{
  "system_name": "String (Top level model name, No Spaces)",
  "components": [
    { 
      "name": "String (Unique Block Name)", 
      "type": "String (Choose from: Inport, Outport, Gain, Sum, Integrator, Subsystem, StateflowChart, ModelReference, Constant, Scope)", 
      "parameters": { "Key": "Value" }, 
      "position": [left, top, right, bottom] (Generate logical coordinates so blocks don't overlap) 
    }
  ],
  "connections": [
    { "source": "BlockName/1", "destination": "BlockName/1" }
  ]
}

LOGIC RULES:
1. If code has 'if/else' state logic, use "StateflowChart".
2. If code has 'functions' or 'classes', use "Subsystem" or "ModelReference".
3. If code has math (PID, Feedforward), use Gain/Sum/Integrator blocks.
"""

def get_ai_response(user_input):
    try:
        model = genai.GenerativeModel('gemini-1.5-pro')
        # Combine System Prompt + User Data
        full_prompt = SYSTEM_PROMPT + "\n\nUSER INPUT DATA:\n" + user_input
        
        response = model.generate_content(full_prompt)
        
        # Clean response to ensure it's pure JSON
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"AI Generation Error: {str(e)}")
        return None

# ==========================================
# 4. FRONTEND UI
# ==========================================

st.title("🚀 GenAI MBD Architect")
st.markdown("### Automated C-Code & Requirements to Simulink Converter")

# Create Tabs
tab1, tab2 = st.tabs(["✨ AI Generator", "📂 Re-Use / Viewer"])

# --- TAB 1: AI GENERATION ---
with tab1:
    st.info("Upload Legacy C/C++ files OR paste Requirements to generate an architecture.")
    
    input_method = st.radio("Select Input:", ["Upload C/C++ Files", "Paste Requirements/Text"])
    
    user_data = ""
    
    if input_method == "Upload C/C++ Files":
        files = st.file_uploader("Drop .c, .cpp, .h files here", accept_multiple_files=True)
        if files:
            for f in files:
                user_data += f"\n// FILE: {f.name}\n" + f.read().decode("utf-8")
            st.success(f"Loaded {len(files)} code files.")
            
    else:
        user_data = st.text_area("Paste System Requirements here:", height=200, placeholder="e.g. The system shall control motor speed using a PID loop...")

    # The "Magic" Button
    if st.button("Generate Architecture ⚡"):
        if not user_data:
            st.error("Please provide input data first!")
        else:
            with st.spinner("AI is architecting the solution..."):
                json_result = get_ai_response(user_data)
                
                if json_result:
                    # Parse
                    mermaid_code = json_to_mermaid(json_result)
                    matlab_code = json_to_matlab(json_result)
                    json_str = json.dumps(json_result, indent=2)
                    
                    st.success("Architecture Designed Successfully!")
                    
                    # Visual
                    st.subheader("1. Visual Architecture (Mermaid)")
                    st.markdown(f"```mermaid\n{mermaid_code}\n```")
                    
                    # Downloads
                    st.subheader("2. Export Artifacts")
                    c1, c2, c3 = st.columns(3)
                    c1.download_button("📥 Download JSON (Save for later)", json_str, "mbd_model.json", "application/json")
                    c2.download_button("📥 Download .m Script (Run in MATLAB)", matlab_code, "build_model.m", "text/plain")
                    c3.download_button("📥 Download Diagram Code", mermaid_code, "diagram.mmd", "text/plain")

                    with st.expander("Peek at the Generated MATLAB Code"):
                        st.code(matlab_code, language='matlab')

# --- TAB 2: JSON VIEWER (NO AI) ---
with tab2:
    st.info("Upload a previously generated JSON file to view or regenerate scripts instantly (No AI usage).")
    
    uploaded_json = st.file_uploader("Upload .json Model File", type=["json"])
    
    if uploaded_json:
        try:
            data = json.load(uploaded_json)
            
            # Instant Parsing
            m_code = json_to_mermaid(data)
            mat_code = json_to_matlab(data)
            
            st.success("Model Loaded!")
            st.markdown(f"```mermaid\n{m_code}\n```")
            
            d1, d2 = st.columns(2)
            d1.download_button("📥 Download .m Script", mat_code, "build_model.m", "text/plain")
            d2.download_button("📥 Download Diagram", m_code, "diagram.mmd", "text/plain")
            
        except Exception as e:
            st.error(f"Invalid JSON File: {e}")
