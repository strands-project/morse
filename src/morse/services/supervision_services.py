import logging; logger = logging.getLogger("morse." + __name__)
from morse.core.services import service
from morse.core import status, blenderapi
from morse.blender.main import reset_objects as main_reset, close_all as main_close, quit as main_terminate
from morse.core.exceptions import *
import json
import mathutils

@service(component = "simulation")
def list_robots():
    """ Return a list of the robots in the current scenario

    Uses the list generated during the initialisation of the scenario
    """
    return [obj.name for obj in blenderapi.persistantstorage().robotDict.keys()]

@service(component = "simulation")
def reset_objects():
    """ Restore all simulation objects to their original position

    Upon receiving the request using sockets, call the
    'reset_objects' function located in morse/blender/main.py
    """
    contr = blenderapi.controller()
    main_reset(contr)
    return "Objects restored to initial position"

@service(component = "simulation")
def quit():
    """ Cleanly quit the simulation
    """
    contr = blenderapi.controller()
    main_close(contr)
    main_terminate(contr)

@service(component = "simulation")
def terminate():
    """ Terminate the simulation (no finalization done!)
    """
    contr = blenderapi.controller()
    main_terminate(contr)

@service(component = "simulation")
def activate(component_name):
    """ Enable the functionality of the component specified
    """
    try:
        blenderapi.persistantstorage().componentDict[component_name]._active = True
    except KeyError as detail:
        logger.warn("Component %s not found. Can't activate" % detail)
        raise MorseRPCTypeError("Component %s not found. Can't activate" % detail)

@service(component = "simulation")
def deactivate(component_name):
    """ Stop the specified component from calling its default_action method
    """
    try:
        blenderapi.persistantstorage().componentDict[component_name]._active = False
    except KeyError as detail:
        logger.warn("Component %s not found. Can't deactivate" % detail)
        raise MorseRPCTypeError("Component %s not found. Can't deactivate" % detail)

@service(component = "simulation")
def suspend_dynamics():
    """ Suspends physics for all object in the scene.
    """

    scene = blenderapi.scene()
    for object in scene.objects:
        object.suspendDynamics()

    return "Physics is suspended"

@service(component = "simulation")
def restore_dynamics():
    """ Resumes physics for all object in the scene.
    """

    scene = blenderapi.scene()
    for object in scene.objects:
        object.restoreDynamics()

    return "Physics is resumed"

@service(component = "simulation")
def details():
    """Returns a structure containing all possible details
    about the simulation currently running, including
    the list of robots, the list of services and datastreams,
    the list of middleware in use, etc.
    """

    simu = blenderapi.persistantstorage()
    details = {}


    # Retrieves the list of services and associated middlewares
    services = {}
    services_iface = {}
    for n, i in simu.morse_services.request_managers().items():
        services.update(i.services())
        for cmpt in i.services():
            services_iface.setdefault(cmpt, []).append(n)

    def cmptdetails(c):
        c = simu.componentDict[c.name]
        cmpt = {"type": type(c).__name__,}
        if c.name() in services:
            cmpt["services"] = services[c.name()]
            cmpt["service_interfaces"] = services_iface[c.name()]

        if c.name() in simu.datastreams:
            stream = simu.datastreams[c.name()]
            cmpt["stream"] = stream[0]
            cmpt["stream_interfaces"] = stream[1]

        return cmpt

    def robotdetails(r):
        robot = {"name": r.name(),
                "type": type(r).__name__,
                "components": {c.name:cmptdetails(c) for c in r.components},
                }
        if r.name() in services:
            robot["services"] = services[r.name()]
            robot["services_interfaces"] = services_iface[r.name()]
        return robot

    for n, i in simu.datastreamDict.items():
        pass


    details['robots'] = [robotdetails(r) for n, r in simu.robotDict.items()]
    return details


@service(component = "simulation")
def set_log_level(component, level):
    """
    Allow to change the logger level of a specific component

    :param string component: the name of the logger you want to modify
    :param string level: the desired level of logging
    """

    my_logger = logging.getLogger('morse.' + component)
    try:
        my_logger.setLevel(level)
    except ValueError as exn:
        raise MorseRPCInvokationError(str(exn))


def get_structured_children_of(blender_object):
    """ Returns a nested dictionary of the given objects children, recursively.
    The retun format is as follows:

    {blender_object.name: [children_dictionary, position, orientation]}

    where children_dictionary is another of the same format, but with the keys
    being the children of blender_object. This continues down the entire tree
    structure.

    :param KX_GameObject blender_object: The Blender object to return children
    for.
    """
    children = blender_object.children
    orientation = blender_object.worldOrientation.to_quaternion()
    position = blender_object.worldPosition
    structure = { blender_object.name: [{},
                                        (position.x, position.y, position.z),
                                        (orientation.x, orientation.y,
                                         orientation.z, orientation.w)
                                        ]
                }
    for c in children:
        structure[blender_object.name][0].update(
            get_structured_children_of(c) )
    return structure

@service(component="simulation")
def get_scene_objects():
    """ Returns a hierarchial dictonary structure of all objects in the scene
    along with their positions and orientations, formated as a Python string
    representation.
    The structure:
    {object_name: [dict_of_children, position_tuple, quaternion_tuple],
    object_name: [dict_of_children, position_tuple, quaternion_tuple],
    ...}
    """

    scene = blenderapi.scene()
    # Special Morse items to remove from the list
    remove_items = ['Scene_Script_Holder', 'CameraFP', '__default__cam__']
    top_levelers = [o for o in scene.objects
                    if o.parent is None and
                    not o.name in remove_items]

    objects = {}
    for obj in top_levelers:
        objects.update(get_structured_children_of(obj))

    return objects

def get_obj_by_name(name):
    """
    Return object in the scene associated to :param name:
    If it does not exists, throw a MorseRPCInvokationError
    """
    scene = blenderapi.scene()
    if name not in scene.objects:
        raise MorseRPCInvokationError(
                "Object '%s' does not appear in the scene." % name)
    return scene.objects[name]

@service(component="simulation")
def set_object_visibility(object_name, visible, do_children):
    """ Set the visibility of an object in the simulation.

    Note: The object will still have physics and dynamics despite being invisible.

    :param string object_name: The name of the object to change visibility of.
    :param visible boolean: Make the object visible(True) or invisible(False)
    :param do_children boolean: If True then the visibility of all children of
    object_name is also set."""

    blender_object = get_obj_by_name(object_name)
    blender_object.setVisible(visible, do_children)
    return visible

@service(component="simulation")
def set_object_dynamics(object_name, state):
    """ Enable or disable the dynamics for an individual object.

    Note: When turning on dynamics, the object will continue with the velocities
    it had when it was turned off.

    :param string object_name: The name of the object to change.
    :param state boolean: Turn on dynamics(True), or off (False)
    """

    blender_object = get_obj_by_name(object_name)
    if state:
        blender_object.restoreDynamics()
    else:
        blender_object.suspendDynamics()
    return state

@service(component="simulation")
def get_object_pose(object_name):
    """ Returns the pose of the object as a tuple of the object's position and
    orientation: [[x, y, z], [qw, qx, qy, qz]]

    :param string object_name: The name of the object.
    """
    b_obj = get_obj_by_name(object_name)

    pos =  b_obj.worldPosition 
    ori =  b_obj.worldOrientation.to_quaternion()

    return json.dumps([[pos.x, pos.y, pos.z], [ori.w,ori.x,ori.y,ori.z]])

@service(component="simulation")
def set_object_pose(object_name, position, orientation):
    """ Sets the pose of the object.

    :param string object_name: The name of the object.
    :param string position: new position of the object [x, y, z]
    :param string position: new orientation of the object [qw, qx, qy, qz]
    """
    b_obj = get_obj_by_name(object_name)

    pos = mathutils.Vector(json.loads(position))
    ori = mathutils.Quaternion(json.loads(orientation)).to_matrix()
     
    # Suspend Physics of that object
    b_obj.suspendDynamics()
    b_obj.setLinearVelocity([0.0, 0.0, 0.0], True)
    b_obj.setAngularVelocity([0.0, 0.0, 0.0], True)
    b_obj.applyForce([0.0, 0.0, 0.0], True)
    b_obj.applyTorque([0.0, 0.0, 0.0], True)
    
    logger.debug("%s goes to %s" % (b_obj, pos))
    b_obj.worldPosition = pos
    b_obj.worldOrientation = ori
    # Reset physics simulation
    b_obj.restoreDynamics()


@service(component="simulation")
def get_object_global_bbox(object_name):
    """ Returns the global bounding box of an object as list encapsulated as
    string: "[[x0, y0, z0 ], ... ,[x7, y7, z7]]".

    :param string object_name: The name of the object.
    """
    # Test whether the object exists in the scene  
    b_obj = get_obj_by_name(object_name)
    
    # Get bounding box of object
    bb = blenderapi.objectdata(object_name).bound_box

    # Group x,y,z-coordinates as lists 
    bbox_local = [[bb_corner[i] for i in range(3)] for bb_corner in bb]
    
    world_pos = b_obj.worldPosition
    world_ori = b_obj.worldOrientation.to_3x3()

    bbox_global = []
    for corner in bbox_local:
        vec = world_ori * mathutils.Vector(corner) + \
            mathutils.Vector(world_pos) 
        bbox_global.append([vec.x,vec.y,vec.z])
        
    return json.dumps(bbox_global)
    
@service(component="simulation")
def get_object_bbox(object_name):
    """ Returns the local bounding box of an object as list encapsulated as
    string: "[[x0, y0, z0 ], ... ,[x7, y7, z7]]".

    :param string object_name: The name of the object.
    """
    # Test whether the object exists in the scene  
    get_obj_by_name(object_name)
    
    # Get bounding box of object
    bb = blenderapi.objectdata(object_name).bound_box

    # Group x,y,z-coordinates as lists 
    bbox_local = [[bb_corner[i] for i in range(3)] for bb_corner in bb]

    return json.dumps(bbox_local)

@service(component="simulation")
def get_object_type(object_name):
    """ Returns the type of an object as string

    :param string object_name: The name of the object.
    """
    # Test whether the object exists in the scene  
    b_obj = get_obj_by_name(object_name)
    
    obj_type = b_obj.get('Type', '')

    return json.dumps(obj_type)

@service(component="simulation")
def transform_to_obj_frame(object_name, point):
    """ Transforms a 3D point with respect to the origin into the coordinate
    frame of an object and returns the global coordinates.

    :param string object_name: The name of the object.
    :param string point: coordinates as a list "[x, y, z]"
    """
    # Test whether the object exists in the scene  
    b_obj = get_obj_by_name(object_name)
    
    world_pos = b_obj.worldPosition
    world_ori = b_obj.worldOrientation.to_3x3()

    pos =  world_ori * mathutils.Vector(json.loads(point)) + \
        mathutils.Vector(world_pos)

    return [pos.x,pos.y,pos.z]
