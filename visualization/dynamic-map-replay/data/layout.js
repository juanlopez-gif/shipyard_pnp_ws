window.ShipyardLayout = {
  viewBox: { width: 1080, height: 660 },
  sourceRefs: [],
  notes: [
    "Edit geometry here: x/y move an object, w/h resize it, label controls visible text.",
    "Visible labels use physical names; internal resource IDs stay hidden in the browser UI.",
    "The dashed reach circles from the reference image are intentionally omitted.",
    "Vision devices and fiducial markers are not drawn in this conference layout."
  ],
  nodes: [
    {
      id: "initial_stack",
      label: "INITIAL\nSTACK",
      kind: "item_stack",
      x: 42,
      y: 70,
      w: 300,
      h: 170,
      statusKey: "initial_stack",
      statusBadge: { x: 112, y: 260, w: 210, align: "left" }
    },
    {
      id: "conveyor1",
      label: "CONVEYOR 1",
      kind: "conveyor",
      x: 370,
      y: 120,
      w: 286,
      h: 56,
      statusKey: "conveyor1",
      statusBadge: { x: 455, y: 194, w: 220, align: "left" },
      sensors: [
        { id: "c1s1", x: 396, y: 120 },
        { id: "c1s2", x: 628, y: 120 }
      ]
    },
    {
      id: "conveyor1_entry",
      label: "Conveyor 1 entry",
      kind: "anchor",
      x: 396,
      y: 148,
      visible: false
    },
    {
      id: "conveyor1_exit",
      label: "Conveyor 1 exit",
      kind: "anchor",
      x: 628,
      y: 148,
      visible: false
    },
    {
      id: "xarm2",
      label: "xArm2",
      kind: "robot",
      robotType: "xarm",
      x: 190,
      y: 276,
      w: 92,
      h: 72,
      statusKey: "xarm2",
      statusBadge: { x: 86, y: 366, w: 260, align: "left" }
    },
    {
      id: "xarm2_gripper",
      label: "xArm2 gripper",
      kind: "anchor",
      x: 236,
      y: 312,
      visible: false
    },
    {
      id: "conveyor3",
      label: "CONVEYOR 3",
      kind: "conveyor",
      x: 382,
      y: 248,
      w: 60,
      h: 184,
      labelRotation: 90,
      statusKey: "conveyor3",
      statusBadge: { x: 492, y: 340, w: 170, rotate: -90 }
    },
    {
      id: "conveyor3_entry",
      label: "Conveyor 3 entry",
      kind: "anchor",
      x: 412,
      y: 266,
      visible: false
    },
    {
      id: "conveyor3_exit",
      label: "Conveyor 3 exit",
      kind: "anchor",
      x: 412,
      y: 414,
      visible: false
    },
    {
      id: "c3_location",
      label: "Conveyor 3 sensor",
      kind: "anchor",
      x: 412,
      y: 340,
      visible: false,
      statusKey: "c3"
    },
    {
      id: "robot2",
      label: "Niryo 2",
      kind: "robot",
      robotType: "niryo",
      x: 760,
      y: 438,
      w: 92,
      h: 72,
      statusKey: "robot2",
      statusBadge: { x: 744, y: 528, w: 230, align: "left" }
    },
    {
      id: "robot2_gripper",
      label: "Niryo 2 gripper",
      kind: "anchor",
      x: 806,
      y: 474,
      visible: false
    },
    {
      id: "xarm1",
      label: "xArm1",
      kind: "robot",
      robotType: "xarm",
      x: 682,
      y: 58,
      w: 92,
      h: 72,
      statusKey: "xarm1",
      statusBadge: { x: 676, y: 42, w: 230, align: "left" }
    },
    {
      id: "xarm1_gripper",
      label: "xArm1 gripper",
      kind: "anchor",
      x: 728,
      y: 94,
      visible: false
    },
    {
      id: "laser_bed",
      label: "LASER\nENGRAVER",
      kind: "laser",
      x: 538,
      y: 204,
      w: 170,
      h: 150,
      statusKey: "laser",
      statusBadge: { x: 560, y: 374, w: 220, align: "left" }
    },
    {
      id: "conveyor2",
      label: "CONVEYOR 2",
      kind: "conveyor",
      x: 804,
      y: 132,
      w: 60,
      h: 260,
      labelRotation: 90,
      statusKey: "conveyor2",
      statusBadge: { x: 884, y: 268, w: 190, align: "left" },
      sensors: [
        { id: "c2s1", x: 864, y: 160 },
        { id: "c2s2", x: 864, y: 360 }
      ]
    },
    {
      id: "conveyor2_entry",
      label: "Conveyor 2 entry",
      kind: "anchor",
      x: 834,
      y: 160,
      visible: false
    },
    {
      id: "conveyor2_exit",
      label: "Conveyor 2 exit",
      kind: "anchor",
      x: 834,
      y: 360,
      visible: false
    },
    {
      id: "intermediate_blue_stack",
      label: "BLUE\nBUFFER",
      kind: "ibs",
      x: 896,
      y: 322,
      w: 150,
      h: 76,
      statusKey: "intermediate_blue_stack",
      statusBadge: { x: 884, y: 418, w: 190, align: "left" },
      slotLayout: { rows: 1, cols: 5, capacity: 5, padX: 12, padY: 38, gap: 6 },
      stackColor: "blue"
    },
    {
      id: "conveyor4",
      label: "CONVEYOR 4",
      kind: "conveyor",
      x: 492,
      y: 452,
      w: 230,
      h: 56,
      statusKey: "conveyor4",
      statusBadge: { x: 607, y: 542, w: 210 }
    },
    {
      id: "conveyor4_entry",
      label: "Conveyor 4 entry",
      kind: "anchor",
      x: 710,
      y: 480,
      visible: false
    },
    {
      id: "conveyor4_exit",
      label: "Conveyor 4 exit",
      kind: "anchor",
      x: 504,
      y: 480,
      visible: false
    },
    {
      id: "c4_location",
      label: "Conveyor 4 sensor",
      kind: "anchor",
      x: 607,
      y: 480,
      visible: false,
      statusKey: "c4"
    },
    {
      id: "robot1",
      label: "Niryo 1",
      kind: "robot",
      robotType: "niryo",
      x: 282,
      y: 464,
      w: 92,
      h: 72,
      statusKey: "robot1",
      statusBadge: { x: 214, y: 448, w: 240, align: "left" }
    },
    {
      id: "robot1_gripper",
      label: "Niryo 1 gripper",
      kind: "anchor",
      x: 328,
      y: 500,
      visible: false
    },
    {
      id: "bantam_bed",
      label: "BANTAM\nCNC",
      kind: "bantam",
      x: 790,
      y: 552,
      w: 130,
      h: 74,
      statusKey: "bantam",
      statusBadge: { x: 790, y: 646, w: 200, align: "left" }
    },
    {
      id: "bantam_door",
      label: "Door",
      kind: "anchor",
      x: 855,
      y: 552,
      visible: false,
      statusKey: "bantam_door"
    },
    {
      id: "submarine_left",
      label: "Submarine Module",
      kind: "submarine",
      x: 126,
      y: 542,
      w: 108,
      h: 94,
      visible: false
    },
    {
      id: "submarine_right",
      label: "Submarine Module",
      kind: "submarine",
      x: 260,
      y: 542,
      w: 108,
      h: 94,
      visible: false
    },
    {
      id: "final_red_stack",
      label: "RED\nFINAL",
      kind: "output_stack",
      x: 86,
      y: 544,
      w: 118,
      h: 90,
      statusKey: "final_red_stack",
      statusBadge: { x: 78, y: 648, w: 128, align: "left", maxLines: 2 },
      slotLayout: { rows: 2, cols: 3, capacity: 6, padX: 10, padY: 36, gap: 6 },
      stackColor: "red"
    },
    {
      id: "final_blue_stack",
      label: "BLUE\nFINAL",
      kind: "output_stack",
      x: 348,
      y: 544,
      w: 118,
      h: 90,
      statusKey: "final_blue_stack",
      statusBadge: { x: 340, y: 648, w: 128, align: "left", maxLines: 2 },
      slotLayout: { rows: 2, cols: 3, capacity: 6, padX: 10, padY: 36, gap: 6 },
      stackColor: "blue"
    },
    {
      id: "final_green_stack",
      label: "GREEN\nFINAL",
      kind: "output_stack",
      x: 217,
      y: 544,
      w: 118,
      h: 90,
      statusKey: "final_green_stack",
      statusBadge: { x: 209, y: 648, w: 128, align: "left", maxLines: 2 },
      slotLayout: { rows: 2, cols: 3, capacity: 6, padX: 10, padY: 36, gap: 6 },
      stackColor: "green"
    },
    {
      id: "robot1_scrap",
      label: "Scrap",
      kind: "anchor",
      x: 996,
      y: 596,
      visible: false,
      statusKey: "robot1_scrap"
    }
  ],
  pickDropoffMarkers: [
    "conveyor1_entry",
    "conveyor1_exit",
    "conveyor2_entry",
    "conveyor2_exit",
    "conveyor3_entry",
    "conveyor3_exit",
    "conveyor4_entry",
    "conveyor4_exit",
    "c4_location"
  ],
  routes: [
    {
      id: "red",
      label: "RED route",
      color: "RED",
      nodes: ["initial_stack", "conveyor1_entry", "conveyor1_exit", "laser_bed", "conveyor2_entry", "conveyor2_exit", "conveyor4_entry", "conveyor4_exit", "final_red_stack"]
    },
    {
      id: "blue",
      label: "BLUE route",
      color: "BLUE",
      nodes: ["initial_stack", "conveyor1_entry", "conveyor1_exit", "conveyor2_entry", "conveyor2_exit", "bantam_bed", "conveyor4_entry", "conveyor4_exit", "final_blue_stack"]
    },
    {
      id: "blue",
      label: "BLUE buffer branch",
      color: "BLUE",
      nodes: ["conveyor2_exit", "intermediate_blue_stack", "bantam_bed"]
    },
    {
      id: "green",
      label: "GREEN route",
      color: "GREEN",
      nodes: ["initial_stack", "xarm2_gripper", "conveyor3_entry", "conveyor3_exit", "final_green_stack"]
    }
  ],
  teachingActions: [
    {
      id: "teach_xarm2_red_to_c1",
      actor: "xarm2",
      title: "Feed RED To Conveyor 1",
      label: "xArm2 feeds a red piece from Initial Stack to Conveyor 1 entry.",
      color: "RED",
      from: "initial_stack",
      to: "conveyor1_entry",
      demoPath: ["initial_stack", "xarm2_gripper", "conveyor1_entry"],
      highlightResources: ["xarm2", "initial_stack", "conveyor1", "conveyor1_entry"],
      condition: "xArm2 is idle, the Initial Stack contains a red piece, and Conveyor 1 entry is available.",
      decision: "The part enters the red/blue line through Conveyor 1.",
      conditions: [
        { label: "xArm2", value: "Idle", state: "AVAILABLE" },
        { label: "Initial Stack", value: "RED piece available", state: "READY" },
        { label: "Conveyor 1 entry", value: "Available", state: "FREE" }
      ]
    },
    {
      id: "teach_xarm2_blue_to_c1",
      actor: "xarm2",
      title: "Feed BLUE To Conveyor 1",
      label: "xArm2 feeds a blue piece from Initial Stack to Conveyor 1 entry.",
      color: "BLUE",
      from: "initial_stack",
      to: "conveyor1_entry",
      demoPath: ["initial_stack", "xarm2_gripper", "conveyor1_entry"],
      highlightResources: ["xarm2", "initial_stack", "conveyor1", "conveyor1_entry"],
      condition: "xArm2 is idle, the Initial Stack contains a blue piece, and Conveyor 1 entry is available.",
      decision: "The part enters the blue machining path through Conveyor 1.",
      conditions: [
        { label: "xArm2", value: "Idle", state: "AVAILABLE" },
        { label: "Initial Stack", value: "BLUE piece available", state: "READY" },
        { label: "Conveyor 1 entry", value: "Available", state: "FREE" }
      ]
    },
    {
      id: "teach_xarm2_green_to_c3",
      actor: "xarm2",
      title: "Feed GREEN To Conveyor 3",
      label: "xArm2 feeds a green piece from Initial Stack to Conveyor 3 entry.",
      color: "GREEN",
      from: "initial_stack",
      to: "conveyor3_entry",
      demoPath: ["initial_stack", "xarm2_gripper", "conveyor3_entry"],
      highlightResources: ["xarm2", "initial_stack", "conveyor3", "conveyor3_entry"],
      condition: "xArm2 is idle, the Initial Stack contains a green piece, and Conveyor 3 entry is available.",
      decision: "The green part bypasses xArm1, Laser, Conveyor 2, Niryo 2, and Bantam.",
      conditions: [
        { label: "xArm2", value: "Idle", state: "AVAILABLE" },
        { label: "Initial Stack", value: "GREEN piece available", state: "READY" },
        { label: "Conveyor 3 entry", value: "Available", state: "FREE" }
      ]
    },
    {
      id: "teach_c1_move",
      actor: "conveyor1",
      title: "Move Along Conveyor 1",
      label: "Conveyor 1 moves a piece from entry zone to exit zone.",
      color: "BLUE",
      from: "conveyor1_entry",
      to: "conveyor1_exit",
      demoPath: ["conveyor1_entry", "conveyor1_exit"],
      highlightResources: ["conveyor1", "conveyor1_entry", "conveyor1_exit"],
      condition: "Conveyor 1 entry is occupied and Conveyor 1 exit is clear.",
      decision: "The conveyor advances only if the exit zone can receive the part.",
      conditions: [
        { label: "Conveyor 1 entry", value: "Occupied", state: "OCCUPIED" },
        { label: "Conveyor 1 exit", value: "Clear", state: "FREE" }
      ]
    },
    {
      id: "teach_xarm1_blue_to_c2",
      actor: "xarm1",
      title: "Move BLUE To Conveyor 2",
      label: "xArm1 moves a blue piece from Conveyor 1 exit to Conveyor 2 entry.",
      color: "BLUE",
      caseType: "Fixed action",
      priorityOrder: 2,
      from: "conveyor1_exit",
      to: "conveyor2_entry",
      demoPath: ["conveyor1_exit", "xarm1_gripper", "conveyor2_entry"],
      highlightResources: ["xarm1", "conveyor1", "conveyor1_exit", "conveyor2", "conveyor2_entry", "laser_bed"],
      condition: "xArm1 is idle, Conveyor 1 exit contains a blue piece, Conveyor 2 entry is available, and no completed laser part is waiting.",
      decision: "In fixed mode, xArm1 handles Conveyor 1 only when the higher-priority laser retrieval is not ready.",
      priority: "Fixed xArm1 priority is LASER_TO_C2S1 before C1S2 handling.",
      conditions: [
        { label: "xArm1", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 1 exit", value: "BLUE piece present", state: "OCCUPIED" },
        { label: "Conveyor 2 entry", value: "Available", state: "FREE" },
        { label: "Laser engraver", value: "No completed part waiting", state: "EMPTY" }
      ]
    },
    {
      id: "teach_xarm1_red_to_laser",
      actor: "xarm1",
      title: "Load RED Into Laser",
      label: "xArm1 moves a red piece from Conveyor 1 exit to the laser engraver.",
      color: "RED",
      caseType: "Fixed action",
      priorityOrder: 3,
      from: "conveyor1_exit",
      to: "laser_bed",
      demoPath: ["conveyor1_exit", "xarm1_gripper", "laser_bed"],
      highlightResources: ["xarm1", "conveyor1", "conveyor1_exit", "laser_bed"],
      condition: "xArm1 is idle, Conveyor 1 exit contains a red piece, and the laser bed is idle and empty.",
      decision: "Red parts enter the laser only when the laser is not already holding a completed part.",
      priority: "Fixed xArm1 priority is LASER_TO_C2S1 before C1S2 handling; this action is only ready when the laser is idle.",
      conditions: [
        { label: "xArm1", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 1 exit", value: "RED piece present", state: "OCCUPIED" },
        { label: "Laser engraver", value: "Idle and empty", state: "FREE" }
      ]
    },
    {
      id: "teach_laser_process_red",
      actor: "laser",
      title: "Process RED",
      label: "The laser engraver processes a red piece on the laser bed.",
      type: "work",
      color: "RED",
      at: "laser_bed",
      demoPath: ["laser_bed"],
      highlightResources: ["laser_bed"],
      condition: "A red piece is loaded and the laser engraver is idle.",
      decision: "The laser starts the required red-part operation.",
      conditions: [
        { label: "Laser engraver", value: "Idle", state: "AVAILABLE" },
        { label: "Laser bed", value: "RED piece loaded", state: "OCCUPIED" }
      ]
    },
    {
      id: "teach_xarm1_laser_to_c2",
      actor: "xarm1",
      title: "Conflict: Laser Before C1",
      label: "xArm1 unloads the completed red laser part to Conveyor 2 before taking the blue part from Conveyor 1 exit.",
      color: "RED",
      caseType: "Fixed conflict",
      priorityOrder: 1,
      from: "laser_bed",
      to: "conveyor2_entry",
      demoPath: ["laser_bed", "xarm1_gripper", "conveyor2_entry"],
      highlightResources: ["xarm1", "laser_bed", "conveyor1", "conveyor1_exit", "conveyor2", "conveyor2_entry"],
      condition: "xArm1 is idle, Conveyor 2 entry is available, the laser has completed a red part, and Conveyor 1 exit also contains a blue part.",
      decision: "Fixed priority selects LASER_TO_C2S1 first, so the completed laser output is cleared before the Conveyor 1 blue part.",
      priority: "Fixed xArm1 priority order: 1) LASER_TO_C2S1, 2) C1S2 handling.",
      conditions: [
        { label: "Laser engraver", value: "Finished RED part", state: "FINISHED" },
        { label: "xArm1", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 2 entry", value: "Available", state: "FREE" },
        { label: "Conveyor 1 exit", value: "BLUE piece also present", state: "OCCUPIED" }
      ],
      conflictPieces: [
        {
          id: "teach_xarm1_conflict_blue_c1",
          location: "conveyor1_exit",
          color: "BLUE",
          label: "B",
          note: "deferred C1 part",
          labelOffset: { x: -92, y: -30 }
        }
      ],
      deferredActions: [
        {
          label: "xArm1 could move the BLUE piece from Conveyor 1 exit to Conveyor 2 entry.",
          reason: "Deferred because LASER_TO_C2S1 has higher fixed priority."
        }
      ]
    },
    {
      id: "teach_c2_move",
      actor: "conveyor2",
      title: "Move Along Conveyor 2",
      label: "Conveyor 2 moves a piece from entry zone to exit zone.",
      color: "RED",
      from: "conveyor2_entry",
      to: "conveyor2_exit",
      demoPath: ["conveyor2_entry", "conveyor2_exit"],
      highlightResources: ["conveyor2", "conveyor2_entry", "conveyor2_exit"],
      condition: "Conveyor 2 entry is occupied and Conveyor 2 exit is clear.",
      decision: "The conveyor advances only if Niryo 2's pickup zone can receive the part.",
      conditions: [
        { label: "Conveyor 2 entry", value: "Occupied", state: "OCCUPIED" },
        { label: "Conveyor 2 exit", value: "Clear", state: "FREE" }
      ]
    },
    {
      id: "teach_robot2_blue_to_bantam",
      actor: "robot2",
      title: "Route BLUE To CNC",
      label: "Niryo 2 moves a blue piece from Conveyor 2 exit to the Bantam CNC.",
      color: "BLUE",
      caseType: "Fixed P1",
      priorityOrder: 2,
      from: "conveyor2_exit",
      to: "bantam_bed",
      demoPath: ["conveyor2_exit", "robot2_gripper", "bantam_bed"],
      highlightResources: ["robot2", "conveyor2", "conveyor2_exit", "conveyor4", "bantam_bed"],
      condition: "Niryo 2 is idle, Conveyor 2 exit contains a blue piece, Conveyor 4 is clear, and Bantam is idle and empty.",
      decision: "Fixed priority selects P1, then places the blue part directly into Bantam because the CNC can receive it.",
      priority: "Fixed Niryo 2 priority order: 1) classify C2 exit, 2) clear Bantam to C4, 3) feed Bantam from Blue Buffer.",
      conditions: [
        { label: "Niryo 2", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 2 exit", value: "BLUE piece present", state: "OCCUPIED" },
        { label: "Conveyor 4", value: "Clear", state: "FREE" },
        { label: "Bantam CNC", value: "Idle and empty", state: "FREE" }
      ]
    },
    {
      id: "teach_robot2_blue_to_buffer",
      actor: "robot2",
      title: "Conflict: C2 Exit To Buffer",
      label: "Niryo 2 moves the blue piece from Conveyor 2 exit to Blue Buffer before clearing a completed Bantam part.",
      color: "BLUE",
      caseType: "Fixed conflict",
      priorityOrder: 1,
      from: "conveyor2_exit",
      to: "intermediate_blue_stack",
      demoPath: ["conveyor2_exit", "robot2_gripper", "intermediate_blue_stack"],
      highlightResources: ["robot2", "conveyor2", "conveyor2_exit", "conveyor4", "conveyor4_entry", "bantam_bed", "intermediate_blue_stack"],
      condition: "Niryo 2 is idle, Conveyor 2 exit contains a blue piece, Conveyor 4 is clear, Bantam contains a finished blue part, and Blue Buffer has free capacity.",
      decision: "Fixed priority selects P1 before P2; because Bantam cannot receive the new blue part, P1 places it in Blue Buffer.",
      priority: "Fixed Niryo 2 priority order: 1) classify C2 exit, 2) clear Bantam to C4, 3) feed Bantam from Blue Buffer.",
      conditions: [
        { label: "Niryo 2", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 2 exit", value: "BLUE piece present", state: "OCCUPIED" },
        { label: "Conveyor 4 entry", value: "Available", state: "FREE" },
        { label: "Bantam CNC", value: "Finished BLUE part waiting", state: "FINISHED" },
        { label: "Blue Buffer", value: "Free slot, max capacity 5", state: "FREE" }
      ],
      conflictPieces: [
        {
          id: "teach_robot2_conflict_blue_bantam",
          location: "bantam_bed",
          color: "BLUE",
          label: "B",
          note: "finished CNC part",
          labelOffset: { x: -76, y: -34 }
        }
      ],
      deferredActions: [
        {
          label: "Niryo 2 could clear the completed Bantam part to Conveyor 4.",
          reason: "Deferred because P1, classifying the waiting Conveyor 2 exit piece, has higher fixed priority than P2."
        }
      ]
    },
    {
      id: "teach_robot2_buffer_to_bantam",
      actor: "robot2",
      title: "Feed CNC From Blue Buffer",
      label: "Niryo 2 moves the oldest buffered blue piece from Blue Buffer to Bantam CNC.",
      color: "BLUE",
      caseType: "Fixed P3",
      priorityOrder: 5,
      from: "intermediate_blue_stack",
      to: "bantam_bed",
      demoPath: ["intermediate_blue_stack", "robot2_gripper", "bantam_bed"],
      highlightResources: ["robot2", "intermediate_blue_stack", "bantam_bed", "conveyor2", "conveyor2_exit", "conveyor4", "conveyor4_entry"],
      condition: "Niryo 2 is idle, Bantam is idle and empty, Blue Buffer contains at least one blue part, and no higher-priority P1/P2 action is ready.",
      decision: "Fixed mode feeds Bantam from the Blue Buffer only after Conveyor 2 exit and completed Bantam output are not competing.",
      priority: "Fixed Niryo 2 priority order: 1) classify C2 exit, 2) clear Bantam to C4, 3) feed Bantam from Blue Buffer.",
      conditions: [
        { label: "Niryo 2", value: "Idle", state: "AVAILABLE" },
        { label: "Blue Buffer", value: "BLUE part waiting", state: "OCCUPIED" },
        { label: "Bantam CNC", value: "Idle and empty", state: "FREE" },
        { label: "Conveyor 2 exit", value: "No ready part", state: "EMPTY" },
        { label: "Conveyor 4 entry", value: "Not needed by P3", state: "CLEAR" }
      ]
    },
    {
      id: "teach_robot2_red_to_c4",
      actor: "robot2",
      title: "Route RED To Conveyor 4",
      label: "Niryo 2 moves a red piece from Conveyor 2 exit to Conveyor 4 entry.",
      color: "RED",
      caseType: "Fixed P1",
      priorityOrder: 3,
      from: "conveyor2_exit",
      to: "conveyor4_entry",
      demoPath: ["conveyor2_exit", "robot2_gripper", "conveyor4_entry"],
      highlightResources: ["robot2", "conveyor2", "conveyor2_exit", "conveyor4", "conveyor4_entry", "bantam_bed"],
      condition: "Niryo 2 is idle, Conveyor 2 exit contains a red piece, Conveyor 4 is clear, and any lower-priority Bantam/Buffer action waits.",
      decision: "Fixed priority selects P1, so the Conveyor 2 exit part is routed to Conveyor 4 before lower-priority work.",
      priority: "Fixed Niryo 2 priority order: 1) classify C2 exit, 2) clear Bantam to C4, 3) feed Bantam from Blue Buffer.",
      conditions: [
        { label: "Niryo 2", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 2 exit", value: "RED piece present", state: "OCCUPIED" },
        { label: "Conveyor 4 entry", value: "Available", state: "FREE" },
        { label: "Bantam CNC", value: "Lower-priority if also finished", state: "WAITING" }
      ],
      conflictPieces: [
        {
          id: "teach_robot2_conflict_blue_bantam_red_case",
          location: "bantam_bed",
          color: "BLUE",
          label: "B",
          note: "deferred CNC part",
          labelOffset: { x: -76, y: -34 }
        }
      ],
      deferredActions: [
        {
          label: "Niryo 2 could clear a completed Bantam part to Conveyor 4.",
          reason: "Deferred whenever P1 is ready, because fixed mode always handles Conveyor 2 exit first."
        }
      ]
    },
    {
      id: "teach_bantam_process_blue",
      actor: "bantam",
      title: "Machine BLUE",
      label: "The Bantam CNC machines a blue piece on the CNC bed.",
      type: "work",
      color: "BLUE",
      at: "bantam_bed",
      demoPath: ["bantam_bed"],
      highlightResources: ["bantam_bed"],
      condition: "A blue piece is loaded and the Bantam CNC is idle.",
      decision: "The CNC starts the required blue-part operation.",
      conditions: [
        { label: "Bantam CNC", value: "Idle", state: "AVAILABLE" },
        { label: "CNC bed", value: "BLUE piece loaded", state: "OCCUPIED" }
      ]
    },
    {
      id: "teach_robot2_bantam_to_c4",
      actor: "robot2",
      title: "Clear CNC To Conveyor 4",
      label: "Niryo 2 moves the machined blue piece from Bantam CNC to Conveyor 4 entry.",
      color: "BLUE",
      caseType: "Fixed P2",
      priorityOrder: 4,
      from: "bantam_bed",
      to: "conveyor4_entry",
      demoPath: ["bantam_bed", "robot2_gripper", "conveyor4_entry"],
      highlightResources: ["robot2", "bantam_bed", "conveyor2", "conveyor2_exit", "conveyor4", "conveyor4_entry"],
      condition: "Bantam has completed a blue part, Conveyor 4 entry is available, and Conveyor 2 exit has no ready part.",
      decision: "Fixed mode only clears Bantam when P1 is not ready; then P2 moves the completed blue part to Conveyor 4.",
      priority: "Fixed Niryo 2 priority order: 1) classify C2 exit, 2) clear Bantam to C4, 3) feed Bantam from Blue Buffer.",
      conditions: [
        { label: "Bantam CNC", value: "Finished BLUE part", state: "FINISHED" },
        { label: "Niryo 2", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 4 entry", value: "Available", state: "FREE" },
        { label: "Conveyor 2 exit", value: "No ready part", state: "EMPTY" }
      ]
    },
    {
      id: "teach_c4_move",
      actor: "conveyor4",
      title: "Move Along Conveyor 4",
      label: "Conveyor 4 moves a finished piece from entry zone to exit zone.",
      color: "RED",
      from: "conveyor4_entry",
      to: "conveyor4_exit",
      demoPath: ["conveyor4_entry", "conveyor4_exit"],
      highlightResources: ["conveyor4", "conveyor4_entry", "conveyor4_exit"],
      condition: "Conveyor 4 entry is occupied and Conveyor 4 exit is clear.",
      decision: "The conveyor advances only if Niryo 1's pickup zone can receive the part.",
      conditions: [
        { label: "Conveyor 4 entry", value: "Occupied", state: "OCCUPIED" },
        { label: "Conveyor 4 exit", value: "Clear", state: "FREE" }
      ]
    },
    {
      id: "teach_robot1_red_to_final",
      actor: "robot1",
      title: "Unload RED Final",
      label: "Niryo 1 moves a red piece from Conveyor 4 exit to Red Final.",
      color: "RED",
      caseType: "Fixed unload",
      priorityOrder: 1,
      from: "conveyor4_exit",
      to: "final_red_stack",
      demoPath: ["conveyor4_exit", "robot1_gripper", "final_red_stack"],
      highlightResources: ["robot1", "conveyor4", "conveyor4_exit", "final_red_stack"],
      condition: "Niryo 1 is idle, Conveyor 4 exit contains a finished red piece, and Red Final has space.",
      decision: "Niryo 1 unloads the finished red part into the red output area.",
      priority: "Fixed Niryo 1 chooses the ready finished conveyor; if C3 and C4 are both ready, the one that settled first wins, with C4 used as the tie-break.",
      conditions: [
        { label: "Niryo 1", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 4 exit", value: "RED piece present", state: "OCCUPIED" },
        { label: "Red Final", value: "Free output slot", state: "FREE" }
      ]
    },
    {
      id: "teach_robot1_blue_to_final",
      actor: "robot1",
      title: "Unload BLUE Final",
      label: "Niryo 1 moves a blue piece from Conveyor 4 exit to Blue Final.",
      color: "BLUE",
      caseType: "Fixed unload",
      priorityOrder: 2,
      from: "conveyor4_exit",
      to: "final_blue_stack",
      demoPath: ["conveyor4_exit", "robot1_gripper", "final_blue_stack"],
      highlightResources: ["robot1", "conveyor4", "conveyor4_exit", "final_blue_stack"],
      condition: "Niryo 1 is idle, Conveyor 4 exit contains a finished blue piece, and Blue Final has space.",
      decision: "Niryo 1 unloads the finished blue part into the blue output area.",
      priority: "Fixed Niryo 1 chooses the ready finished conveyor; if C3 and C4 are both ready, the one that settled first wins, with C4 used as the tie-break.",
      conditions: [
        { label: "Niryo 1", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 4 exit", value: "BLUE piece present", state: "OCCUPIED" },
        { label: "Blue Final", value: "Free output slot", state: "FREE" }
      ]
    },
    {
      id: "teach_robot1_green_to_final",
      actor: "robot1",
      title: "Unload GREEN Final",
      label: "Niryo 1 moves a green piece from Conveyor 3 exit to Green Final.",
      color: "GREEN",
      caseType: "Fixed unload",
      priorityOrder: 3,
      from: "conveyor3_exit",
      to: "final_green_stack",
      demoPath: ["conveyor3_exit", "robot1_gripper", "final_green_stack"],
      highlightResources: ["robot1", "conveyor3", "conveyor3_exit", "final_green_stack"],
      condition: "Niryo 1 is idle, Conveyor 3 exit contains a finished green piece, Green Final has space, and no earlier-settled C4 job is waiting.",
      decision: "Niryo 1 unloads the bypassed green part into the green output area.",
      priority: "Fixed Niryo 1 chooses the ready finished conveyor; if C3 and C4 are both ready, the one that settled first wins, with C4 used as the tie-break.",
      conditions: [
        { label: "Niryo 1", value: "Idle", state: "AVAILABLE" },
        { label: "Conveyor 3 exit", value: "GREEN piece present", state: "OCCUPIED" },
        { label: "Green Final", value: "Free output slot", state: "FREE" }
      ]
    }
  ]
};
