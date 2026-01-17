# 规划/进度更新 planning
import json


def get_planning_prompt(
    instruction: str,
    planning_json: dict | None,
    operation_history: list,
    action_history: list,
    completed_summary: str,
    last_reflect_label: str,
    last_reflect_reason: str,
):
    prompt = "You are a mobile GUI agent PLANNER. Your job is NOT to decide coordinates.\n"

    if not planning_json:
        prompt += "Your job is to: build a subtask plan.\n\n"

        prompt += "### USER INSTRUCTION ###\n"
        prompt += instruction.strip() + "\n\n"

        prompt += "### PLANNING RULES ###\n"
        prompt += "1) Create a plan by decomposing the instruction into ordered subtasks and initialize progress.\n"
        prompt += "2) Each subtask MUST have a stable app_name used for memory category, e.g., 'Setting', 'QQ', 'Maps', 'Chrome'.\n"
        prompt += "3) Each subtask must be atomic, verifiable, and can be done by one action.\n"
        prompt += "4) Always output STRICT JSON only. No extra text.\n\n"

        prompt += "### OUTPUT JSON SCHEMA (STRICT) ###\n"
        prompt += """{
              "subtasks": [
                {
                  "id": <int>,
                  "title": "<short subtask title>",
                  "app_name": "<app name>",
                  "done": <true/false>
                }
              ],
              "progress": {
                "completed_ids": [<int>],
                "completed_summary": "<short summary of what is done so far>",
                "current_id": <int or null>,
                "current_subtask": "<string or empty>",
                "current_app_name": "<string or empty>",
                "has_replanned_this_iteration": <true/false>,
                "replan_reason": "<string>"
              }
            }"""
        return prompt

    prompt += "Your job is to: (1) update subtask plan if needed, (2) track progress, (3) select the current subtask for this iteration.\n\n"

    prompt += "### USER INSTRUCTION ###\n"
    prompt += instruction.strip() + "\n\n"

    prompt += "### CURRENT PLAN JSON ###\n"
    prompt += (json.dumps(planning_json, ensure_ascii=False) if planning_json else "null") + "\n\n"

    prompt += "### EXECUTION HISTORY (most recent last) ###\n"
    if operation_history:
        for i in range(len(operation_history)):
            op = operation_history[i].replace("\n", " ").strip()
            act = action_history[i].replace("\n", " ").strip() if i < len(action_history) else ""
            prompt += f"- Step-{i+1}: operation='{op}' ; action='{act}'\n"
    else:
        prompt += "- (none)\n"
    prompt += "\n"

    prompt += "### COMPLETED SUMMARY (may be empty) ###\n"
    prompt += (completed_summary.strip() if completed_summary else "") + "\n\n"

    prompt += "### LAST REFLECTION RESULT ###\n"
    prompt += f"label={last_reflect_label}(A means The result of Operation meets the expectation; B means the Operation results in a wrong page; C means The Operation produces no changes). Reason={last_reflect_reason}\n\n"

    prompt += "### PLANNING RULES ###\n"
    prompt += "1) Update each subtask.done and progress based on the EXECUTION HISTORY and COMPLETED SUMMARY.\n"
    prompt += "2) Select current task as the first subtask with done=false.\n"
    prompt += "3) If error=True: consider whether remaining subtasks require revision.\n"
    prompt += "4) Only revise FUTURE tasks when clearly necessary; keep already-done tasks stable.\n"
    prompt += "5) Always output STRICT JSON only. No extra text.\n\n"

    prompt += "### OUTPUT JSON SCHEMA (STRICT) ###\n"
    prompt += """{
      "subtasks": [
        {
          "id": <int>,
          "title": "<short subtask title>",
          "app_id": "<app name>",
          "done": <true/false>
        }
      ],
      "progress": {
        "completed_summary": "<short summary of what is done so far>",
        "completed_ids": [<int>],
        "current_id": <int or null>,
        "current_app_name": "<string or empty>",
        "current_subtask": "<string or empty>",
        "has_replanned_this_iteration": <true/false>,
        "replan_reason": "<string>"
      }
    }"""

    return prompt


# decision
def get_decision_prompt(
    instruction, width, height, keyboard,
    operation_history, action_history,
    last_operation, last_action,
    add_info,
    last_reflect_label, last_reflect_reason, error, completed,
    current_app_name,
    current_subtask,
    important_content,
    retrieved_memory,
    ):
    prompt = "### Background ###\n"
    prompt += f"The image is a phone screenshot. Its width is {width} pixels and its height is {height} pixels. The user\'s instruction is: {instruction}.\n\n"
    prompt += "The format of the coordinates is [x, y], x is the pixel from left to right and y is the pixel from top to bottom. "

    if current_subtask or current_app_name:
        prompt += "### Current subtask ###\n"
        prompt += "In this iteration, you must focus on the CURRENT subtask only (not the whole instruction).\n"
        prompt += f"Current app: {current_app_name}\n"
        prompt += f"Current subtask: {current_subtask}\n\n"

    prompt += "### Keyboard status ###\n"
    prompt += "We extract the keyboard status of the current screenshot and it is whether the keyboard of the current screenshot is activated.\n"
    prompt += "The keyboard status is as follow:\n"
    if keyboard:
        prompt += "The keyboard has been activated and you can type."
    else:
        prompt += "The keyboard has not been activated and you can\'t type."
    prompt += "\n\n"
    
    if add_info != "":
        prompt += "### Hint ###\n"
        prompt += "There are hints to help you complete the user\'s instructions. The hints are as follow:\n"
        prompt += add_info
        prompt += "\n\n"
    
    if len(action_history) > 0:
        prompt += "### History operations ###\n"
        prompt += "Before reaching this page, some operations have been completed. You need to refer to the completed operations to decide the next operation. These operations are as follow:\n"
        for i in range(len(action_history)):
            prompt += f"Step-{i+1}: [Operation: " + operation_history[i].split(" to ")[0].strip() + "; Action: " + action_history[i] + "]\n"
        prompt += "\n"
    
    if completed != "":
        prompt += "### Progress ###\n"
        prompt += "After completing the history operations, you have the following thoughts about the progress of user\'s instruction completion:\n"
        prompt += "Completed contents:\n" + completed + "\n\n"



    if retrieved_memory:
        prompt += "### Retrieved memory (reference only) ###\n"
        prompt += retrieved_memory + "\n"
        prompt += "Use this as HIGH-LEVEL guidance (UI path / semantic target). Do NOT reuse old coordinates blindly.\n"
        prompt += "Always decide based on the CURRENT screenshot.\n\n"

        prompt += "### Critical rule about memory ###\n"
        prompt += "If retrieved memory contains coordinates, treat them as outdated hints.\n"
        prompt += "You MUST re-locate the correct UI element on the current screenshot and output fresh coordinates.\n\n"

    if important_content != "":
        prompt += "### Important Contents ###\n"
        prompt += "During the operations, you record the following contents on the screenshot for use in subsequent operations:\n"
        prompt += "Important Contents:\n" + important_content + "\n"

    prompt += "### LAST REFLECTION RESULT ###\n"
    prompt += f"label={last_reflect_label}(A means The result of Operation meets the expectation; B means the Operation results in a wrong page; C means The Operation produces no changes). Reason={last_reflect_reason}\n\n"
    if error:
        prompt += "### Last operation ###\n"
        prompt += f"You previously attempted to perform the operation \"{last_operation}\" by executing the Action \"{last_action}\". That action was incorrect, and its effect has already been undone. Now, you should not repeat “{last_action}” or perform a similar back-off action. Instead, re-evaluate the current screen and choose a new action that advances the task toward the goal."
        prompt += "\n\n"

    prompt += "### Response requirements ###\n"
    prompt += "Now you need to combine all of the above to perform just one action on the current page. You must choose one of the five actions below:\n"
    prompt += "Open app 'app name' (x, y): If the current page is desktop, you can use this action to tap the position (x, y) in current page to open the app named \"app name\" on the desktop.\n"
    prompt += "Tap (x, y): Tap the position (x, y) in current page.\n"
    prompt += "Swipe (x1, y1), (x2, y2): Swipe from position (x1, y1) to position (x2, y2).\n"
    if keyboard:
        prompt += "Type (text): Type the \"text\" in the input box.\n"
    else:
        prompt += "Unable to Type. You cannot use the action \"Type\" because the keyboard has not been activated. If you want to type, please first activate the keyboard by tapping on the input box on the screen.\n"
    prompt += "Home: Return to home page.\n"
    prompt += "\n\n"
    
    prompt += "### Output format ###\n"
    prompt += "Your output consists of the following three parts:\n"
    prompt += "### Thought ###\nThink about the requirements that have been completed in previous operations and the requirements that need to be completed in the next one operation.\n"
    prompt += "### Action ###\nYou can only choose one from the five actions above. Make sure that the coordinates or text in the \"()\".\n"
    prompt += "### Description ###\nPlease generate a brief natural language description for the operation in Action based on your Thought."
    
    return prompt


def get_reflect_prompt(instruction, width, height, keyboard1, keyboard2, operation, action, add_info):
    prompt = f"These images are two phone screenshots before and after an operation. Their widths are {width} pixels and their heights are {height} pixels.\n\n"
    
    prompt += "In order to help you better perceive the content in this screenshot, we extract some information on the current screenshot through system files. "
    prompt += "The information consists of two parts, consisting of format: coordinates; content. "
    prompt += "The format of the coordinates is [x, y], x is the pixel from left to right and y is the pixel from top to bottom; the content is a text or an icon description respectively "
    prompt += "The keyboard status is whether the keyboard of the current page is activated."
    prompt += "\n\n"
    
    prompt += "### Before the current operation ###\n"
    prompt += "Screenshot information:\n"

    prompt += "Keyboard status:\n"
    if keyboard1:
        prompt += f"The keyboard has been activated."
    else:
        prompt += "The keyboard has not been activated."
    prompt += "\n\n"
            
    prompt += "### After the current operation ###\n"
    prompt += "Screenshot information:\n"

    prompt += "Keyboard status:\n"
    if keyboard2:
        prompt += f"The keyboard has been activated."
    else:
        prompt += "The keyboard has not been activated."
    prompt += "\n\n"
    
    prompt += "### Current operation ###\n"
    prompt += f"The user\'s instruction is: {instruction}. You also need to note the following requirements: {add_info}. In the process of completing the requirements of instruction, an operation is performed on the phone. Below are the details of this operation:\n"
    prompt += "Operation thought: " + operation.split(" to ")[0].strip() + "\n"
    prompt += "Operation action: " + action
    prompt += "\n\n"
    
    prompt += "### Response requirements ###\n"
    prompt += "Now you need to output the following content based on the screenshots before and after the current operation:\n"
    prompt += "Whether the result of the \"Operation action\" meets your expectation of \"Operation thought\"?\n"
    prompt += "A: The result of the \"Operation action\" meets my expectation of \"Operation thought\".\n"
    prompt += "B: The \"Operation action\" results in a wrong page and I need to return to the previous page.\n"
    prompt += "C: The \"Operation action\" produces no changes."
    prompt += "\n\n"
    
    prompt += "### Output format ###\n"
    prompt += "Your output format is:\n"
    prompt += "### Thought ###\nYour thought about the question\n"
    prompt += "### Answer ###\nA or B or C"
    
    return prompt


# memory
def get_memory_prompt(
    instruction: str,
    current_app_name: str,
    current_subtask: str,
    reflect_thought: str,
    operation: str,
    action: str
):
    """
    Long-term Skill Memory writer prompt.
    Output STRICT JSON only. No coordinates. No step-by-step for the whole instruction.
    Focus on reusable guidance for similar subtasks in the same app category.
    """
    prompt = "You are writing LONG-TERM SKILL MEMORY for a mobile GUI agent.\n"
    prompt += "This memory will be reused across many future tasks, not just this session.\n\n"

    prompt += "### CONTEXT (for grounding only) ###\n"
    prompt += f"App category (memory namespace): {current_app_name}\n"
    prompt += f"Current subtask (from planner): {current_subtask}\n"
    prompt += f"User instruction (original, may be long): {instruction}\n"
    prompt += f"Executed action (may include coordinates): {action}\n"
    prompt += f"Executed operation description: {operation}\n"
    prompt += f"Reflection thought (why it worked): {reflect_thought}\n"

    prompt += "=== WHAT TO WRITE ===\n"
    prompt += "Write a reusable skill entry that helps the agent complete similar subtasks in the SAME app category in the future.\n"
    prompt += "The entry must be short, stable, and not dependent on this exact screen layout.\n\n"

    prompt += "=== HARD RULES ===\n"
    prompt += "1) Do NOT include any coordinates (x,y) or pixel numbers.\n"
    prompt += "2) Do NOT mention specific one-off UI states like transient popups unless truly general.\n"
    prompt += "3) Prefer semantic cues: menu names, settings section names, icons meaning, search keywords.\n"
    prompt += "4) If there are multiple common UI variants, mention alternatives briefly.\n"
    prompt += "5) Keep each field concise (1-3 sentences max).\n\n"

    prompt += "=== OUTPUT (STRICT JSON ONLY) ===\n"
    prompt += """{
  "when_to_use": "<when this skill applies (conditions, app page context, keywords)>",
  "hint": "<reusable operational guidance: how to locate the target and what to do>",
  "avoid": "<common mistakes or wrong paths to avoid>"
}"""

    return prompt



