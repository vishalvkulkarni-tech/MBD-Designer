import streamlit as st
import google.generativeai as genai
import json
import base64
import re
from pypdf import PdfReader
from docx import Document
import hashlib
from datetime import datetime

# ==========================================
# 1. SETUP & SECURITY
# ==========================================
st.set_page_config(page_title="GenAI MBD Architect", layout="wide", page_icon="⚙️")

# Initialize session state for debugging
if 'debug_mode' not in st.session_state:
    st.session_state['debug_mode'] = False
if 'generation_history' not in st.session_state:
    st.session_state['generation_history'] = []

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
    Renders diagram as a static image via mermaid.ink with enhanced error handling.
    """
    if not mermaid_code or not mermaid_code.strip():
        st.error("❌ Empty Mermaid code - cannot render diagram")
        return
    
    try:
        # Validate mermaid syntax before rendering
        if not mermaid_code.startswith('graph'):
            st.warning("⚠️ Mermaid code may be malformed (missing 'graph' declaration)")
        
        # Check for minimum content
        lines = [l.strip() for l in mermaid_code.split('\n') if l.strip()]
        if len(lines) < 2:
            st.error("❌ Mermaid diagram has no content (only header line)")
            st.code(mermaid_code, language='mermaid')
            return
        
        graphbytes = mermaid_code.encode("utf8")
        base64_bytes = base64.b64encode(graphbytes)
        base64_string = base64_bytes.decode("ascii")
        url = "https://mermaid.ink/img/" + base64_string
        
        st.image(url, caption="System Architecture", use_container_width=True)
        
    except Exception as e:
        st.error(f"❌ Could not render visual diagram: {str(e)}")
        st.warning("Please check the diagram code below for syntax errors.")
    
    with st.expander("🔍 View/Edit Diagram Code"):
        edited_mermaid = st.text_area("Mermaid Code", mermaid_code, height=300, key="mermaid_editor")
        if st.button("Re-render Diagram"):
            st.rerun()

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

# Mermaid reserved keywords that need special handling
MERMAID_KEYWORDS = {'end', 'graph', 'subgraph', 'style', 'class', 'click', 'call', 'direction', 'TB', 'TD', 'BT', 'RL', 'LR'}

def sanitize_id(text):
    """
    Enhanced sanitization:
    1. Removes special chars
    2. Handles reserved keywords
    3. Ensures valid identifier
    4. Creates unique hash for duplicate names
    """
    if not text or not text.strip():
        return f"id_{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:8]}"
    
    # Remove special characters
    clean_text = re.sub(r'[^a-zA-Z0-9_]', '', text)
    
    # Ensure doesn't start with number
    if clean_text and clean_text[0].isdigit():
        clean_text = 'n' + clean_text
    
    # Handle reserved keywords
    if clean_text.lower() in MERMAID_KEYWORDS:
        clean_text = f"block_{clean_text}"
    
    # Add prefix for safety
    return f"id_{clean_text}" if clean_text else f"id_{hashlib.md5(text.encode()).hexdigest()[:8]}"

def sanitize_label(text):
    """Enhanced label sanitization for Mermaid display."""
    if not text:
        return "Unknown"
    # Replace problematic characters
    text = text.replace('"', "'")
    text = text.replace('\n', ' ')
    text = text.replace('\r', '')
    # Limit length for readability
    if len(text) > 50:
        text = text[:47] + "..."
    return text

def validate_json_structure(data):
    """
    Validates the JSON structure from AI response.
    Returns (is_valid, error_message)
    """
    if not isinstance(data, dict):
        return False, "Response is not a JSON object"
    
    if 'system_name' not in data:
        return False, "Missing 'system_name' field"
    
    if 'components' not in data:
        return False, "Missing 'components' field"
    
    if not isinstance(data['components'], list):
        return False, "'components' must be a list"
    
    for i, comp in enumerate(data['components']):
        if not isinstance(comp, dict):
            return False, f"Component {i} is not an object"
        if 'name' not in comp:
            return False, f"Component {i} missing 'name'"
        if 'type' not in comp:
            return False, f"Component {i} missing 'type'"
    
    if 'connections' in data and not isinstance(data['connections'], list):
        return False, "'connections' must be a list"
    
    return True, "Valid"

def json_to_mermaid(data):
    """
    Enhanced Mermaid converter with error handling and validation.
    """
    try:
        # Validate data structure
        is_valid, error_msg = validate_json_structure(data)
        if not is_valid:
            raise ValueError(f"Invalid JSON structure: {error_msg}")
        
        mermaid_lines = ["graph LR"]
        
        # Track all node IDs for validation
        node_ids = {}  # Maps safe_id -> original_name
        
        # Nodes
        for idx, comp in enumerate(data.get('components', [])):
            try:
                raw_name = comp.get('name', f'Component_{idx}')
                safe_id = sanitize_id(raw_name)
                
                # Handle duplicate IDs
                if safe_id in node_ids:
                    safe_id = f"{safe_id}_{idx}"
                node_ids[safe_id] = raw_name
                
                label = sanitize_label(raw_name)
                ctype = comp.get('type', 'Unknown')
                
                # Format: SafeID["Readable Name"]
                if ctype == "Subsystem":
                    mermaid_lines.append(f'    {safe_id}(["{label}<br/>Subsystem"])')
                elif ctype == "ModelReference":
                    mermaid_lines.append(f'    {safe_id}[["{label}<br/>ModelRef"]]')
                elif ctype == "StateflowChart":
                    mermaid_lines.append(f'    {safe_id}{{\"{label}<br/>Stateflow\"}}')
                elif ctype == "Inport":
                    mermaid_lines.append(f'    {safe_id}(["{label}"])')
                elif ctype == "Outport":
                    mermaid_lines.append(f'    {safe_id}(["{label}"])')
                else:
                    mermaid_lines.append(f'    {safe_id}["{label}"]')
            except Exception as e:
                if st.session_state.get('debug_mode'):
                    st.warning(f"⚠️ Skipping component {idx}: {str(e)}")
                continue
        
        # Connections with better error handling
        valid_connections = 0
        for idx, conn in enumerate(data.get('connections', [])):
            try:
                # Handle "Block/Port" format by splitting
                src_raw = str(conn.get('source', '')).split('/')[0]
                dst_raw = str(conn.get('destination', '')).split('/')[0]
                
                if not src_raw or not dst_raw:
                    continue
                
                src_safe = sanitize_id(src_raw)
                dst_safe = sanitize_id(dst_raw)
                
                # Verify nodes exist
                if src_safe not in node_ids:
                    # Try to find matching node
                    for nid, nname in node_ids.items():
                        if nname == src_raw:
                            src_safe = nid
                            break
                    else:
                        if st.session_state.get('debug_mode'):
                            st.warning(f"⚠️ Source '{src_raw}' not found")
                        continue
                
                if dst_safe not in node_ids:
                    # Try to find matching node
                    for nid, nname in node_ids.items():
                        if nname == dst_raw:
                            dst_safe = nid
                            break
                    else:
                        if st.session_state.get('debug_mode'):
                            st.warning(f"⚠️ Destination '{dst_raw}' not found")
                        continue
                
                # Add connection with label if specified
                label = conn.get('label', '')
                if label:
                    mermaid_lines.append(f"    {src_safe} -->|{sanitize_label(label)}| {dst_safe}")
                else:
                    mermaid_lines.append(f"    {src_safe} --> {dst_safe}")
                
                valid_connections += 1
                    
            except Exception as e:
                if st.session_state.get('debug_mode'):
                    st.warning(f"⚠️ Skipping connection {idx}: {str(e)}")
                continue
        
        result = "\n".join(mermaid_lines)
        
        # Log for debugging
        if st.session_state.get('debug_mode'):
            st.info(f"✅ Generated Mermaid with {len(node_ids)} nodes and {valid_connections} connections")
        
        return result
        
    except Exception as e:
        error_msg = f"Error generating Mermaid: {str(e)}"
        st.error(error_msg)
        # Return a minimal valid diagram
        return "graph LR\n    Error[\"Error generating diagram\"]\n"

def json_to_matlab(data):
    """
    Enhanced MATLAB script generator with better error handling and layout.
    """
    try:
        model_name = data.get('system_name', 'GenAI_Model').replace(" ", "_")
        model_name = re.sub(r'[^a-zA-Z0-9_]', '', model_name)  # Remove invalid chars
        
        if not model_name or model_name[0].isdigit():
            model_name = 'M_' + model_name
        
        lines = [
            f"% Auto-Generated MBD Build Script for: {model_name}",
            f"% Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "% ==========================================",
            "",
            "% Close all systems and clear workspace",
            "bdclose all; clear; clc;",
            "",
            f"% Create new system",
            f"new_system('{model_name}');",
            f"open_system('{model_name}');",
            ""
        ]
        
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
            "Scope": "simulink/Sinks/Scope",
            "Product": "simulink/Math Operations/Product",
            "Switch": "simulink/Signal Routing/Switch",
            "Saturation": "simulink/Discontinuities/Saturation"
        }
    
        lines.append("% ========================================== ")
        lines.append("% Add Blocks")
        lines.append("% ==========================================")
        
        # Auto-layout positioning
        x_start, y_start = 100, 100
        x_spacing, y_spacing = 200, 100
        col_count = 0
        
        for idx, comp in enumerate(data.get('components', [])):
            try:
                blk_type = comp.get('type', 'Subsystem')
                blk_name = comp.get('name', f'Block_{idx}').replace(" ", "_")
                blk_name = re.sub(r'[^a-zA-Z0-9_]', '', blk_name)
                
                lib_path = lib_map.get(blk_type, "built-in/Subsystem")
                
                lines.append(f"\n% Adding {blk_type}: {blk_name}")
                lines.append(f"try")
                lines.append(f"    add_block('{lib_path}', '{model_name}/{blk_name}');")
                
                # Apply parameters
                if 'parameters' in comp and isinstance(comp['parameters'], dict):
                    for k, v in comp['parameters'].items():
                        lines.append(f"    set_param('{model_name}/{blk_name}', '{k}', '{v}');")
                
                # Position handling
                if 'position' in comp:
                    pos = str(comp['position']).replace('[', '').replace(']', '')
                    lines.append(f"    set_param('{model_name}/{blk_name}', 'Position', [{pos}]);")
                else:
                    # Auto-layout
                    x = x_start + (col_count % 4) * x_spacing
                    y = y_start + (col_count // 4) * y_spacing
                    lines.append(f"    set_param('{model_name}/{blk_name}', 'Position', [{x}, {y}, {x+80}, {y+40}]);")
                    col_count += 1
                
                lines.append(f"catch ME")
                lines.append(f"    warning('Failed to add block {blk_name}: %s', ME.message);")
                lines.append(f"end")
                
            except Exception as e:
                lines.append(f"% Error processing component {idx}: {str(e)}")
    
        lines.append("\n% ==========================================")
        lines.append("% Connect Blocks")
        lines.append("% ==========================================")
        
        for idx, conn in enumerate(data.get('connections', [])):
            try:
                src = str(conn.get('source', '')).replace(" ", "_")
                dst = str(conn.get('destination', '')).replace(" ", "_")
                
                # Clean connection strings
                src = re.sub(r'[^a-zA-Z0-9_/]', '', src)
                dst = re.sub(r'[^a-zA-Z0-9_/]', '', dst)
                
                if src and dst:
                    lines.append(f"try")
                    lines.append(f"    add_line('{model_name}', '{src}', '{dst}', 'autorouting', 'on');")
                    lines.append(f"catch ME")
                    lines.append(f"    warning('Connection failed {src} -> {dst}: %s', ME.message);")
                    lines.append(f"end")
            except Exception as e:
                lines.append(f"% Error processing connection {idx}: {str(e)}")
    
        lines.append("\n% ==========================================")
        lines.append("% Save and Display")
        lines.append("% ==========================================")
        lines.append(f"save_system('{model_name}');")
        lines.append(f"fprintf('Model {model_name} created successfully!\\n');")
        
        return "\n".join(lines)
        
    except Exception as e:
        error_script = f"% Error generating MATLAB script: {str(e)}\n% Please check the JSON structure."
        st.error(f"Error generating MATLAB script: {str(e)}")
        return error_script

# ==========================================
# 6. AI ENGINE
# ==========================================

# Prompt for Code Files (C/C++/H)
CODE_ANALYSIS_PROMPT = """
You are a Senior MBD (Model-Based Design) Architect specializing in reverse-engineering C/C++ code into Simulink/Stateflow architectures.

CRITICAL TASK: 
Analyze the C/C++ code files and extract the COMPLETE Simulink/Stateflow architecture with ALL components and data flows.

OUTPUT RULES:
1. ONLY output valid JSON - NO markdown, NO code blocks, NO explanations
2. MUST identify MINIMUM 5-10 components (extract everything meaningful)
3. ALL components MUST have proper connections showing data flow
4. Use actual function/variable names from the code

========================================
HOW TO ANALYZE C/C++ CODE:
========================================
- Functions → Subsystems or Gain blocks
- Global variables → Inports/Outports
- Math operations (+, -, *, /) → Sum/Product/Gain
- if/switch statements → Switch blocks or StateflowChart
- Loops/state machines → StateflowChart
- Constants/defines → Constant blocks
- Function parameters → Inports
- Return values → Outports
- Integration/accumulation → Integrator blocks

CODE ANALYSIS EXAMPLES:

Example 1 - Simple Function:
```c
float calculate_speed(float input, float gain) {
    return input * gain;
}
```
EXTRACT:
{
  "system_name": "Speed_Calculator",
  "components": [
    {"name": "SpeedInput", "type": "Inport"},
    {"name": "GainValue", "type": "Constant", "parameters": {"Value": "gain"}},
    {"name": "Multiply", "type": "Product"},
    {"name": "SpeedOutput", "type": "Outport"}
  ],
  "connections": [
    {"source": "SpeedInput/1", "destination": "Multiply/1"},
    {"source": "GainValue/1", "destination": "Multiply/2"},
    {"source": "Multiply/1", "destination": "SpeedOutput/1"}
  ]
}

Example 2 - PID Controller:
```c
float pid_control(float error) {
    static float integral = 0;
    float Kp = 1.0, Ki = 0.1, Kd = 0.01;
    float derivative = error - prev_error;
    integral += error;
    return Kp*error + Ki*integral + Kd*derivative;
}
```
EXTRACT:
{
  "system_name": "PID_Controller",
  "components": [
    {"name": "ErrorInput", "type": "Inport"},
    {"name": "Kp_Gain", "type": "Gain", "parameters": {"Gain": "1.0"}},
    {"name": "Ki_Gain", "type": "Gain", "parameters": {"Gain": "0.1"}},
    {"name": "Kd_Gain", "type": "Gain", "parameters": {"Gain": "0.01"}},
    {"name": "Integrator", "type": "Integrator"},
    {"name": "Derivative", "type": "Subsystem"},
    {"name": "Sum_P_I_D", "type": "Sum"},
    {"name": "ControlOutput", "type": "Outport"}
  ],
  "connections": [
    {"source": "ErrorInput/1", "destination": "Kp_Gain/1"},
    {"source": "ErrorInput/1", "destination": "Integrator/1"},
    {"source": "ErrorInput/1", "destination": "Derivative/1"},
    {"source": "Kp_Gain/1", "destination": "Sum_P_I_D/1"},
    {"source": "Integrator/1", "destination": "Ki_Gain/1"},
    {"source": "Ki_Gain/1", "destination": "Sum_P_I_D/2"},
    {"source": "Derivative/1", "destination": "Kd_Gain/1"},
    {"source": "Kd_Gain/1", "destination": "Sum_P_I_D/3"},
    {"source": "Sum_P_I_D/1", "destination": "ControlOutput/1"}
  ]
}

MANDATORY JSON SCHEMA:
{
  "system_name": "Descriptive_Name_From_Code",
  "components": [
    {
      "name": "ComponentName",
      "type": "Inport|Outport|Gain|Sum|Integrator|Subsystem|StateflowChart|Constant|Scope|Product|Switch|Saturation",
      "parameters": {"Key": "Value"},
      "position": [left, top, right, bottom]
    }
  ],
  "connections": [
    {
      "source": "SourceComponent/1",
      "destination": "DestinationComponent/1",
      "label": "signal_name"
    }
  ]
}

BLOCK TYPE MAPPING:
- Input parameters/globals → Inport
- Output/return values → Outport
- Multiply/divide/scale → Gain or Product
- Add/subtract → Sum
- Accumulation/integration → Integrator
- Complex functions → Subsystem
- State machines/switches → StateflowChart
- Fixed values/defines → Constant
- Limit/clamp → Saturation
- Conditional logic → Switch

CRITICAL INSTRUCTIONS:
- Analyze ALL files together to understand complete system
- Extract EVERY function as a component
- Map ALL data flows between functions
- Identify mathematical operations explicitly
- Create hierarchy with Subsystems for grouped functions
- Use actual names from code (function names, variable names)

MINIMUM OUTPUT: 5-10 components with complete connections showing data flow through the system!
"""

# Prompt for Requirements Documents (PDF/Word/Text)
REQUIREMENTS_PROMPT = """
You are a Senior MBD (Model-Based Design) Architect specializing in converting requirement documents into Simulink/Stateflow architectures.

CRITICAL TASK: 
Analyze the requirement document and design a complete Simulink/Stateflow architecture that implements ALL specified requirements.

OUTPUT RULES:
1. ONLY output valid JSON - NO markdown, NO code blocks, NO explanations
2. MUST identify MINIMUM 4-8 components covering all requirements
3. ALL components MUST have connections showing signal flow
4. Use descriptive names reflecting the requirements

========================================
HOW TO ANALYZE REQUIREMENTS:
========================================
- System inputs mentioned → Inport
- System outputs mentioned → Outport
- Control algorithms (PID, feedback, etc.) → Subsystem
- Mathematical operations mentioned → Gain/Sum/Product/Integrator
- State machines/modes/conditions → StateflowChart
- Sensors/actuators mentioned → Inport/Outport
- Data processing/filtering → Subsystem
- Limit/saturation requirements → Saturation
- Conditional logic → Switch or StateflowChart
- Constants/thresholds mentioned → Constant

REQUIREMENTS EXAMPLE:
"The system shall receive speed command and current speed. It shall calculate the error (command - current). 
The error shall be processed by a PID controller with Kp=1.0, Ki=0.1, Kd=0.01 to generate motor command."

EXTRACT:
{
  "system_name": "Speed_Control_System",
  "components": [
    {"name": "SpeedCommand", "type": "Inport"},
    {"name": "CurrentSpeed", "type": "Inport"},
    {"name": "ErrorCalculation", "type": "Sum", "parameters": {"Inputs": "+-"}},
    {"name": "Proportional", "type": "Gain", "parameters": {"Gain": "1.0"}},
    {"name": "Integral", "type": "Integrator"},
    {"name": "IntegralGain", "type": "Gain", "parameters": {"Gain": "0.1"}},
    {"name": "Derivative", "type": "Subsystem"},
    {"name": "DerivativeGain", "type": "Gain", "parameters": {"Gain": "0.01"}},
    {"name": "PID_Sum", "type": "Sum", "parameters": {"Inputs": "+++"}},
    {"name": "MotorCommand", "type": "Outport"}
  ],
  "connections": [
    {"source": "SpeedCommand/1", "destination": "ErrorCalculation/1"},
    {"source": "CurrentSpeed/1", "destination": "ErrorCalculation/2"},
    {"source": "ErrorCalculation/1", "destination": "Proportional/1"},
    {"source": "ErrorCalculation/1", "destination": "Integral/1"},
    {"source": "ErrorCalculation/1", "destination": "Derivative/1"},
    {"source": "Proportional/1", "destination": "PID_Sum/1"},
    {"source": "Integral/1", "destination": "IntegralGain/1"},
    {"source": "IntegralGain/1", "destination": "PID_Sum/2"},
    {"source": "Derivative/1", "destination": "DerivativeGain/1"},
    {"source": "DerivativeGain/1", "destination": "PID_Sum/3"},
    {"source": "PID_Sum/1", "destination": "MotorCommand/1"}
  ]
}

MANDATORY JSON SCHEMA:
{
  "system_name": "Descriptive_System_Name",
  "components": [
    {
      "name": "ComponentName",
      "type": "Inport|Outport|Gain|Sum|Integrator|Subsystem|StateflowChart|Constant|Scope|Product|Switch|Saturation",
      "parameters": {"Key": "Value"},
      "position": [left, top, right, bottom]
    }
  ],
  "connections": [
    {
      "source": "SourceComponent/1",
      "destination": "DestinationComponent/1",
      "label": "signal_name"
    }
  ]
}

CRITICAL INSTRUCTIONS:
- Read the ENTIRE document to understand system scope
- Identify ALL functional requirements
- Create components for EACH requirement
- Connect components to show complete signal flow
- Include control logic, math operations, and data processing
- Use clear, requirement-based naming

MINIMUM OUTPUT: 4-8 components covering all major requirements with complete signal flow!
"""

def detect_input_type(uploaded_files):
    """
    Detects whether uploaded files are code or requirements based on extensions.
    Returns: 'code' or 'requirements'
    """
    if not uploaded_files:
        return 'requirements'
    
    code_extensions = {'.c', '.cpp', '.h', '.hpp', '.cc', '.cxx'}
    req_extensions = {'.pdf', '.docx', '.doc', '.txt', '.md'}
    
    code_count = 0
    req_count = 0
    
    for file in uploaded_files:
        ext = '.' + file.name.split('.')[-1].lower()
        if ext in code_extensions:
            code_count += 1
        elif ext in req_extensions:
            req_count += 1
    
    # If more code files, use code prompt
    if code_count > req_count:
        return 'code'
    else:
        return 'requirements'

def extract_json_from_text(text):
    """
    Robust JSON extraction from AI response that may contain markdown or extra text.
    """
    try:
        # Try direct parse first
        return json.loads(text)
    except:
        pass
    
    # Remove markdown code blocks
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # Find JSON object boundaries
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except:
            pass
    
    # Try to find JSON array
    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except:
            pass
    
    return None

def get_ai_response(user_input, input_type='requirements', max_retries=3):
    """
    Enhanced AI response handler with retry logic and prompt selection based on input type.
    """
    model_name = st.session_state.get('active_model')
    
    # Select appropriate prompt based on input type
    if input_type == 'code':
        system_prompt = CODE_ANALYSIS_PROMPT
        if st.session_state.get('debug_mode'):
            st.info("🔧 Using CODE analysis prompt")
    else:
        system_prompt = REQUIREMENTS_PROMPT
        if st.session_state.get('debug_mode'):
            st.info("📋 Using REQUIREMENTS analysis prompt")
    
    for attempt in range(max_retries):
        try:
            model = genai.GenerativeModel(
                model_name,
                generation_config={
                    "temperature": 0.3,  # Lower temperature for more consistent JSON
                    "top_p": 0.95,
                    "top_k": 40,
                }
            )
            
            full_prompt = system_prompt + "\n\nUSER INPUT DATA:\n" + user_input[:15000]  # Increased limit for code files
            
            if st.session_state.get('debug_mode'):
                st.info(f"🤖 Attempt {attempt + 1}/{max_retries} - Calling {model_name}")
            
            response = model.generate_content(full_prompt)
            
            if not response or not response.text:
                raise ValueError("Empty response from AI model")
            
            # Extract JSON from response
            json_data = extract_json_from_text(response.text)
            
            if not json_data:
                raise ValueError("Could not extract valid JSON from response")
            
            # Validate structure
            is_valid, error_msg = validate_json_structure(json_data)
            if not is_valid:
                raise ValueError(f"Invalid JSON structure: {error_msg}")
            
            # Success - store in history
            st.session_state['generation_history'].append({
                'timestamp': datetime.now().isoformat(),
                'model': model_name,
                'success': True,
                'attempt': attempt + 1
            })
            
            if st.session_state.get('debug_mode'):
                st.success(f"✅ Successfully generated architecture on attempt {attempt + 1}")
            
            return json_data
            
        except json.JSONDecodeError as e:
            error_msg = f"JSON Parse Error: {str(e)}"
            if attempt < max_retries - 1:
                st.warning(f"⚠️ {error_msg}. Retrying ({attempt + 1}/{max_retries})...")
            else:
                st.error(f"❌ {error_msg} after {max_retries} attempts")
                
        except Exception as e:
            error_msg = f"AI Error: {str(e)}"
            if attempt < max_retries - 1:
                st.warning(f"⚠️ {error_msg}. Retrying ({attempt + 1}/{max_retries})...")
            else:
                st.error(f"❌ {error_msg} after {max_retries} attempts")
                st.error("Please check:\n- API key validity\n- Input file content\n- Network connection")
    
    # All retries failed
    st.session_state['generation_history'].append({
        'timestamp': datetime.now().isoformat(),
        'model': model_name,
        'success': False,
        'attempts': max_retries
    })
    
    return None
  ]
}

CRITICAL INSTRUCTIONS:
- Read the ENTIRE document to understand system scope
- Identify ALL functional requirements
- Create components for EACH requirement
- Connect components to show complete signal flow
- Include control logic, math operations, and data processing
- Use clear, requirement-based naming

MINIMUM OUTPUT: 4-8 components covering all major requirements with complete signal flow!
"""

# ==========================================
# 7. FRONTEND UI
# ==========================================
st.title("🚀 GenAI MBD Architect")
st.markdown("Convert **Requirements** (PDF/Doc) or **Legacy Code** (C/C++) into Simulink Models.")

# Sidebar controls
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    st.session_state['debug_mode'] = st.checkbox("🐛 Debug Mode", value=st.session_state.get('debug_mode', False))
    
    if st.session_state['generation_history']:
        st.markdown("### 📊 Generation History")
        success_count = sum(1 for h in st.session_state['generation_history'] if h.get('success'))
        total_count = len(st.session_state['generation_history'])
        st.metric("Success Rate", f"{success_count}/{total_count}")
        
        if st.button("Clear History"):
            st.session_state['generation_history'] = []
            st.rerun()

tab1, tab2, tab3 = st.tabs(["✨ AI Generator", "📂 Viewer Mode", "ℹ️ Help"])

with tab1:
    st.markdown("### 📤 Upload Input Files")
    uploaded_files = st.file_uploader(
        "Upload Files (Code or Docs)", 
        type=['c', 'cpp', 'h', 'txt', 'pdf', 'docx', 'md'], 
        accept_multiple_files=True,
        help="Upload C/C++ code files or requirement documents (PDF, Word)"
    )
    
    if uploaded_files:
        st.info(f"📁 {len(uploaded_files)} file(s) uploaded")
        with st.expander("View Uploaded Files"):
            for f in uploaded_files:
                st.text(f"• {f.name} ({f.size} bytes)")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        generate_button = st.button("🚀 Generate Architecture", type="primary", use_container_width=True)
    with col2:
        if st.button("🗑️ Clear", use_container_width=True):
            # Clear session state
            if 'last_generation' in st.session_state:
                del st.session_state['last_generation']
            st.rerun()
    
    if generate_button:
        # Clear old results when starting new generation
        if 'last_generation' in st.session_state:
            del st.session_state['last_generation']
        if not uploaded_files:
            st.error("⚠️ Please upload files first!")
        else:
            # Store results in session state
            if 'last_generation' not in st.session_state:
                st.session_state['last_generation'] = {}
            
            user_data = ""
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Read files
            total_chars = 0
            # Detect input type and select appropriate prompt
            input_type = detect_input_type(uploaded_files)
            
            if st.session_state.get('debug_mode'):
                st.info(f"📂 Detected input type: **{input_type.upper()}**")
            
            status_text.text(f"🤖 Generating architecture with AI ({input_type} analysis)...")
            
            with st.spinner(f"Architecting with {st.session_state['active_model']}..."):
                json_result = get_ai_response(user_data, input_type=input_type=======================\n// FILE: {f.name}\n// ==========================================\n{text}\n\n"
                total_chars += len(text)
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            if st.session_state.get('debug_mode'):
                st.info(f"📊 Read {len(uploaded_files)} files, {total_chars:,} characters total")
            
            status_text.text("🤖 Generating architecture with AI...")
            
            with st.spinner(f"Architecting with {st.session_state['active_model']}..."):
                json_result = get_ai_response(user_data)
                
                if json_result:
                    status_text.text("🎨 Creating visualizations...")
                    
                    try:Validate outputs
                        if not mermaid_code or mermaid_code.strip() == "graph LR":
                            raise ValueError("Generated empty Mermaid diagram")
                        
                        # Store in session
                        st.session_state['last_generation'] = {
                            'json': json_result,
                            'mermaid': mermaid_code,
                            'matlab': matlab_code,
                            'json_str': json_str,
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'file_count': len(uploaded_files)
                        }
                        
                        progress_bar.progress(100)
                        status_text.empty()
                        st.success(f"✅ Architecture generated from {len(uploaded_files)} filesd %H:%M:%S')
                        }
                        
                        progress_bar.progress(100)
                        status_text.empty()
                        st.success("✅ Architecture generated successfully!")
                        
                        # Display results
                        st.markdown("---")
                        st.subheader("📊 Visual Architecture")
                        render_mermaid_ui(mermaid_code)
                        
                        st.markdown("---")
                        st.subheader("💾 Export Artifacts")
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.download_button(
                                "📥 JSON Model",
                                json_str,
                                f"mbd_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                                "application/json",
                                use_container_width=True
                            )
                        with col2:
                            st.download_button(
                                "📥 MATLAB Script",
                                matlab_code,
                                f"build_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.m",
                                "text/plain",
                                use_container_width=True
                            )
                        with col3:
                            st.download_button(
                                "📥 Mermaid Diagram",
                                mermaid_code,
                                f"diagram_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mmd",
                                "text/plain",
                                use_container_width=True
                            )
                        
                        # Show JSON structure
                        with st.expander("🔍 View JSON Structure"):
                            st.json(json_result)
                        
                        # Show MATLAB code preview
                        with st.expander("📝 View MATLAB Code"):
                            st.code(matlab_code, language='matlab')
                            
                    except Exception as e:
                        st.error(f"❌ Error generating outputs: {str(e)}")
                        if st.session_state.get('debug_mode'):
                            st.exception(e)
                else:
                    progress_bar.empty()
        gen = st.session_state['last_generation']
        file_info = f" ({gen.get('file_count', 0)} files)" if 'file_count' in gen else ""
        st.info(f"ℹ️ Showing last generation from {gen['timestamp']}{file_info
                    st.error("❌ Failed to generate architecture. Please check your input and try again.")
    
    # Show last generation if available
    elif 'last_generation' in st.session_state and st.session_state['last_generation']:
        st.info(f"ℹ️ Showing last generation from {st.session_state['last_generation']['timestamp']}")
        
        st.markdown("---")
        st.subheader("📊 Visual Architecture")
        render_mermaid_ui(st.session_state['last_generation']['mermaid'])
        
        st.markdown("---")
        st.subheader("💾 Export Artifacts")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button(
                "📥 JSON Model",
                st.session_state['last_generation']['json_str'],
                "mbd_model.json",
                "application/json",
                use_container_width=True
            )
        with col2:
            st.download_button(
                "📥 MATLAB Script",
                st.session_state['last_generation']['matlab'],
                "build_model.m",
                "text/plain",
                use_container_width=True
            )
        with col3:
            st.download_button(
                "📥 Mermaid Diagram",
                st.session_state['last_generation']['mermaid'],
                "diagram.mmd",
                "text/plain",
                use_container_width=True
            )

with tab2:
    st.markdown("### 📂 Load Existing Model")
    uploaded_json = st.file_uploader(
        "Upload .json Model", 
        type=["json"],
        help="Load a previously generated JSON model to view or export"
    )
    
    if uploaded_json:
        try:
            data = json.load(uploaded_json)
            
            # Validate
            is_valid, error_msg = validate_json_structure(data)
            if not is_valid:
                st.error(f"❌ Invalid JSON structure: {error_msg}")
            else:
                st.success(f"✅ Loaded model: {data.get('system_name', 'Unnamed')}")
                
                # Generate outputs
                m_code = json_to_mermaid(data)
                mat_code = json_to_matlab(data)
                json_str = json.dumps(data, indent=2)
                
                st.markdown("---")
                st.subheader("📊 Visual Architecture")
                render_mermaid_ui(m_code)
                
                st.markdown("---")
                st.subheader("💾 Export Artifacts")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.download_button(
                        "📥 JSON Model",
                        json_str,
                        f"{data.get('system_name', 'model')}.json",
                        "application/json",
                        use_container_width=True
                    )
                with col2:
                    st.download_button(
                        "📥 MATLAB Script",
                        mat_code,
                        f"{data.get('system_name', 'model')}.m",
                        "text/plain",
                        use_container_width=True
                    )
                with col3:
                    st.download_button(
                        "📥 Mermaid Diagram",
                        m_code,
                        f"{data.get('system_name', 'model')}.mmd",
                        "text/plain",
                        use_container_width=True
                    )
                
                # Model info
                with st.expander("ℹ️ Model Information"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Components", len(data.get('components', [])))
                    with col2:
                        st.metric("Connections", len(data.get('connections', [])))
                    
                    st.markdown("**Component Types:**")
                    type_counts = {}
                    for comp in data.get('components', []):
                        ctype = comp.get('type', 'Unknown')
                        type_counts[ctype] = type_counts.get(ctype, 0) + 1
                    
                    for ctype, count in sorted(type_counts.items()):
                        st.text(f"  • {ctype}: {count}")
                
                # JSON editor
                with st.expander("✏️ Edit JSON"):
                    edited_json = st.text_area("JSON Content", json_str, height=400)
                    if st.button("Apply Changes"):
                        try:
                            new_data = json.loads(edited_json)
                            is_valid, error_msg = validate_json_structure(new_data)
                            if is_valid:
                                st.success("✅ Changes applied!")
                                st.rerun()
                            else:
                                st.error(f"❌ Invalid JSON: {error_msg}")
                        except json.JSONDecodeError as e:
                            st.error(f"❌ JSON Parse Error: {str(e)}")
                            
        except json.JSONDecodeError as e:
            st.error(f"❌ Invalid JSON file: {str(e)}")
        except Exception as e:
            st.error(f"❌ Error loading file: {str(e)}")
            if st.session_state.get('debug_mode'):
                st.exception(e)

with tab3:
    st.markdown("""
    ## 📖 User Guide
    
    ### 🎯 Purpose
    This tool converts legacy C/C++ code or requirement documents into Simulink/Stateflow models using AI.
    
    ### 🚀 Quick Start
    
    1. **Upload Files** (Tab 1: AI Generator)
       - C/C++ source files (.c, .cpp, .h)
       - Requirement documents (.pdf, .docx, .txt, .md)
       - Multiple files supported
    
    2. **Generate Architecture**
       - Click "Generate Architecture" button
       - AI analyzes your input and creates a model
       - Wait for processing (may take 10-30 seconds)
    
    3. **Review & Export**
       - View the Mermaid diagram visualization
       - Download JSON model structure
       - Download MATLAB script (.m file)
       - Download Mermaid diagram code (.mmd file)
    
    ### 📊 Supported Block Types
    
    | Block Type | Description | Example Use |
    |------------|-------------|-------------|
    | Inport | System inputs | Sensor data, commands |
    | Outport | System outputs | Control signals, results |
    | Gain | Multiplication | Scaling, amplification |
    | Sum | Addition/Subtraction | Error calculation |
    | Integrator | Integration over time | Velocity to position |
    | Subsystem | Grouped blocks | Modular design |
    | StateflowChart | State machine | Mode logic, FSM |
    | Constant | Fixed values | Parameters, thresholds |
    | Scope | Signal visualization | Debugging, monitoring |
    
    ### 💡 Tips for Best Results
    
    1. **Input Quality**
       - Provide well-documented code
       - Include comments explaining functionality
       - For requirements: use clear, structured text
    
    2. **File Organization**
       - Group related files together
       - Include header files for C/C++ code
       - Provide context in README or comments
    
    3. **Troubleshooting**
       - Enable Debug Mode (sidebar) for detailed logs
       - Check generation history for success rate
       - Verify API key is valid
       - Ensure input files are readable
    
    ### 🔧 Using Generated Files
    
    **JSON Model:**
    - Intermediate representation
    - Can be edited manually
    - Reload in Viewer Mode
    
    **MATLAB Script (.m):**
    1. Open MATLAB/Simulink
    2. Navigate to script location
    3. Run the script
    4. Model will be created and opened
    
    **Mermaid Diagram (.mmd):**
    - Open in Mermaid editor
    - Include in documentation
    - Export to PNG/SVG
    
    ### ⚙️ Debug Mode
    
    Enable in sidebar to see:
    - Detailed AI processing steps
    - Component/connection validation
    - Error details and warnings
    - Generation statistics
    
    ### 📝 JSON Structure Example
    
    ```json
    {
      "system_name": "Speed_Controller",
      "components": [
        {
          "name": "SpeedInput",
          "type": "Inport",
          "position": [30, 100, 60, 120]
        },
        {
          "name": "PID_Gain",
          "type": "Gain",
          "parameters": {"Gain": "0.5"},
          "position": [120, 100, 150, 130]
        }
      ],
      "connections": [
        {
          "source": "SpeedInput/1",
          "destination": "PID_Gain/1"
        }
      ]
    }
    ```
    
    ### ❓ Common Issues
    
    **Diagram Not Rendering:**
    - Check for reserved keywords in component names
    - Verify all connections reference existing components
    - View diagram code for syntax errors
    
    **Empty/Invalid Output:**
    - Verify API key is correct
    - Check input files are not empty
    - Try smaller input files
    - Enable debug mode for details
    
    **MATLAB Script Errors:**
    - Ensure Simulink is installed
    - Check block types are valid
    - Verify library paths
    
    ### 📧 Support
    
    For issues or questions:
    - Enable Debug Mode for diagnostics
    - Check generation history
    - Review error messages carefully
    """)

