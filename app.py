import streamlit as st
import google.generativeai as genai
import json
import re

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
st.set_page_config(page_title="GenAI MBD Architect", layout="wide", page_icon="⚙️")

# SIDEBAR: API Key Input (So you don't hardcode it)
st.sidebar.title("Configuration")
api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

if api_key:
    genai.configure(api_key=api_key)

# ==========================================
# 2. CORE PARSING LOGIC (Python Logic)
# ==========================================

def json_to_mermaid(data):
    """Converts JSON Architecture to Mermaid Chart"""
    mermaid_lines = ["graph LR"]
    
    # 1. Create Nodes
    for comp in data.get('components', []):
        name = comp['name']
        ctype = comp['type']
        
        # Styling based on type
        if ctype == "Subsystem":
            line = f"    {name}(({name}<br/>Subsystem))"
        elif ctype == "ModelReference":
            line = f"    {name}[[{name}<br/>ModelRef]]"
        elif ctype == "StateflowChart":
            line = f"    {name}{{ {name}<br/>Stateflow }}"
        elif ctype == "Inport":
            line = f"    {name}([{name}])"
        elif ctype == "Outport":
            line = f"    {name}([{name}])"
        else:
            line = f"    {name}[{name}]"
            
        mermaid_lines.append(line)

    # 2. Create Connections
    for conn in data.get('connections', []):
        src = conn['source'].split('/')[0] # Get block name only
        dst = conn['destination'].split('/')[0]
        mermaid_lines.append(f"    {src} --> {dst}")

    return "\n".join(mermaid_lines)

def json_to_matlab(data):
    """Converts JSON Architecture to Executable MATLAB Script"""
    model_name = data.get('system_name', 'GenAI_Model')
    lines = []
    
    lines.append(f"% Auto-Generated MBD Build Script for: {model_name}")
    lines.append("bdclose all;")
    lines.append(f"new_system('{model_name}');")
    lines.append(f"open_system('{model_name}');")
    
    # Helper to mapping standard types to Simulink Library paths
    # You can expand this library mapping as needed
    lib_map = {
        "Gain": "simulink/Math Operations/Gain",
        "Sum": "simulink/Math Operations/Add",
        "Integrator": "simulink/Continuous/Integrator",
        "Inport": "simulink/Sources/In1",
        "Outport": "simulink/Sinks/Out1",
        "Subsystem": "built-in/Subsystem",
        "ModelReference": "simulink/Ports & Subsystems/Model",
        "StateflowChart": "sflib/Chart" 
    }

    # 1. Add Blocks
    for comp in data.get('components', []):
        blk_type = comp['type']
        blk_name = comp['name']
        
        # Default to a simple Subsystem if type is unknown
        lib_path = lib_map.get(blk_type, "built-in/Subsystem")
        
        lines.append(f"add_block('{lib_path}', '{model_name}/{blk_name}');")
        
        # Set Parameters if they exist
        if 'parameters' in comp:
            for k, v in comp['parameters'].items():
                lines.append(f"set_param('{model_name}/{blk_name}', '{k}', '{v}');")
        
        # Position (Optional, but good for visual layout)
        if 'position' in comp:
            pos = str(comp['position']).replace('[', '').replace(']', '')
            lines.append(f"set_param('{model_name}/{blk_name}', 'Position', [{pos}]);")

    # 2. Add Lines
    lines.append("% Connecting Blocks...")
    for conn in data.get('connections', []):
        lines.append(f"try add_line('{model_name}', '{conn['source']}', '{conn['destination']}', 'autorouting', 'on'); catch; end")

    lines.append("save_system;")
    return "\n".join(lines)

# ==========================================
# 3. AI INTERFACE (The Brain)
# ==========================================

SYSTEM_PROMPT = """
You are a Senior MBD Architect. Your goal is to analyze input data and design a Simulink/Stateflow architecture.
You must ONLY output a valid JSON object strictly adhering to this schema. Do not add markdown like ```json.

SCHEMA:
{
  "system_name": "String",
  "components": [
    { "name": "String", "type": "String (Inport|Outport|Gain|Sum|Integrator|Subsystem|StateflowChart|ModelReference)", "parameters": {}, "position": [x, y, w, h] }
  ],
  "connections": [ { "source": "BlockName/PortNum", "destination": "BlockName/PortNum" } ]
}
"""

def get_ai_response(user_input_text):
    if not api_key:
        return None
    
    model = genai.GenerativeModel('gemini-1.5-pro')
    response = model.generate_content(SYSTEM_PROMPT + "\n\nINPUT DATA:\n" + user_input_text)
    
    # Cleaning the response to ensure raw JSON
    clean_text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_text)

# ==========================================
# 4. STREAMLIT UI LAYOUT
# ==========================================

st.title("🚀 AI-Powered MBD Architect Tool")
st.markdown("Convert **Legacy Code** or **Requirements** into Simulink Models & Diagrams.")

# Tabs for the two utilities
tab1, tab2 = st.tabs(["✨ Generate New Architecture (AI)", "📂 Load Existing Architecture (JSON)"])

# --- TAB 1: AI GENERATION ---
with tab1:
    st.subheader("1. Input Source")
    input_type = st.radio("Select Input Type:", ["C/C++ Code Files", "Requirements (Text/Doc)"])
    
    user_content = ""
    
    if input_type == "C/C++ Code Files":
        uploaded_files = st.file_uploader("Upload .c, .cpp, .h files", accept_multiple_files=True)
        if uploaded_files:
            for f in uploaded_files:
                content = f.read().decode("utf-8")
                user_content += f"\n--- FILE: {f.name} ---\n{content}"
            st.info(f"Loaded {len(uploaded_files)} files.")
            
    else:
        # Requirements Input
        user_content = st.text_area("Paste Requirements or logic here:", height=200)

    if st.button("🚀 Generate Architecture"):
        if not user_content:
            st.error("Please upload files or enter text.")
        elif not api_key:
            st.error("Please enter API Key in the sidebar.")
        else:
            with st.spinner("AI is analyzing logic and designing architecture..."):
                try:
                    # 1. Call AI
                    json_data = get_ai_response(user_content)
                    
                    # 2. Parse Logic
                    mermaid_code = json_to_mermaid(json_data)
                    matlab_code = json_to_matlab(json_data)
                    json_str = json.dumps(json_data, indent=2)
                    
                    st.success("Generation Complete!")
                    
                    # 3. Display Results
                    st.subheader("Visual Architecture")
                    st.markdown(f"```mermaid\n{mermaid_code}\n```")
                    
                    # 4. Download Buttons
                    c1, c2, c3 = st.columns(3)
                    c1.download_button("📥 Download JSON (Re-use)", json_str, "model.json", "application/json")
                    c2.download_button("📥 Download .m Script", matlab_code, "build_model.m", "text/plain")
                    c3.download_button("📥 Download Mermaid", mermaid_code, "diagram.mmd", "text/plain")
                    
                    with st.expander("View MATLAB Script Preview"):
                        st.code(matlab_code, language='matlab')

                except Exception as e:
                    st.error(f"An error occurred: {e}")

# --- TAB 2: RE-USE UTILITY (NO AI) ---
with tab2:
    st.subheader("Upload Existing JSON Architecture")
    st.markdown("This utility does **not** use AI. It purely converts your saved JSON into MATLAB/Mermaid formats.")
    
    json_file = st.file_uploader("Upload .json file", type="json")
    
    if json_file:
        try:
            # 1. Read JSON directly
            json_data = json.load(json_file)
            
            # 2. Parse (Pure Python)
            mermaid_code = json_to_mermaid(json_data)
            matlab_code = json_to_matlab(json_data)
            
            st.success("JSON Parsed Successfully!")
            
            # 3. Display
            st.subheader("Visual Architecture")
            st.markdown(f"```mermaid\n{mermaid_code}\n```")
            
            # 4. Downloads
            c1, c2 = st.columns(2)
            c1.download_button("📥 Download .m Script", matlab_code, "build_model.m", "text/plain")
            c2.download_button("📥 Download Mermaid", mermaid_code, "diagram.mmd", "text/plain")
            
        except Exception as e:
            st.error(f"Invalid JSON File: {e}")
