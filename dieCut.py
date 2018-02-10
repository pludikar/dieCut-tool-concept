#Author-Peter Ludikar
#Description-An Add-In for making dog-bone fillets.

# This version is a proof of concept 

# I've completely revamped the dogbone add-in by Casey Rogers and Patrick Rainsberry and David Liu
# some of the original utilities have remained, but mostly everything else has changed.

# The original add-in was based on creating sketch points and extruding - I found using sketches and extrusion to be very heavy 
# on processing resources, so this version has been designed to create dogbones directly by using a hole tool. So far the
# the performance of this approach is day and night compared to the original version. 

# Select the face you want the dogbones to drop from. Specify a tool diameter and a radial offset.
# The add-in will then create a dogbone with diamater equal to the tool diameter plus
# twice the offset (as the offset is applied to the radius) at each selected edge.

 
from collections import defaultdict

import adsk.core, adsk.fusion
import math
import traceback
import uuid

import time
from . import utils as dbutils

#constants - to keep attribute group and names consistent
DOGBONEGROUP = 'dogBoneGroup'
FACE_ID = 'faceID'
REV_ID = 'revId'
ID = 'id'



class DieToolCommand(object):
    COMMAND_ID = "dieToolBtn"
    
    def __init__(self):
        self.app = adsk.core.Application.get()
        self.ui = self.app.userInterface

        self.offStr = "0"
        self.offVal = None
        self.circStr = "0.25 in"
        self.circVal = None
        self.edges = []
        self.benchmark = False
        self.errorCount = 0
        self.faceSelections = adsk.core.ObjectCollection.create()

        self.handlers = dbutils.HandlerHelper()

    def addButton(self):
        # clean up any crashed instances of the button if existing
        try:
            self.removeButton()
        except:
            pass

        # add add-in to UI
        buttonDieTool = self.ui.commandDefinitions.addButtonDefinition(
            self.COMMAND_ID, 'DieTool', 'Applies profile as tool to cut a body', 'Resources/ShowEntityVertices ')

        buttonDieTool.commandCreated.add(self.handlers.make_handler(adsk.core.CommandCreatedEventHandler,
                                                                    self.onCreate))

        createPanel = self.ui.allToolbarPanels.itemById('SolidCreatePanel')
        buttonControl = createPanel.controls.addCommand(buttonDieTool, 'dieToolBtn')

        # Make the button available in the panel.
        buttonControl.isPromotedByDefault = True
        buttonControl.isPromoted = True

    def removeButton(self):
        cmdDef = self.ui.commandDefinitions.itemById(self.COMMAND_ID)
        if cmdDef:
            cmdDef.deleteMe()
        createPanel = self.ui.allToolbarPanels.itemById('SolidCreatePanel')
        cntrl = createPanel.controls.itemById(self.COMMAND_ID)
        if cntrl:
            cntrl.deleteMe()
            
    def onChange(self, args:adsk.core.InputChangedEventArgs):
        changedInput = adsk.core.CommandInput.cast(args.input)
        if changedInput.id == 'profile':
            changedInput.commandInputs.itemById('centrePoint').hasFocus = True
            return
        if changedInput.id == 'centrePoint':
            changedInput.commandInputs.itemById('directionPoint').hasFocus = True
            return
        if changedInput.id == 'directionPoint':
            changedInput.commandInputs.itemById('targetFace').hasFocus = True
            return
        if changedInput.id == 'targetFace':
            changedInput.commandInputs.itemById('targetPoint').hasFocus = True
            return
        if changedInput.id == 'targetPoint':
            changedInput.commandInputs.itemById('toFace').hasFocus = True
            return
        

    def onCreate(self, args:adsk.core.CommandCreatedEventArgs):
## gets executed on initiation - standard event handler
        inputs = adsk.core.CommandCreatedEventArgs.cast(args)
        self.profile = None
        self.centrePoint = None
        self.directionPoint = None
        self.targetFace = None
        self.targetPoint = None
        self.extent = None
        argsCmd = adsk.core.Command.cast(args)

        inputs = adsk.core.CommandInputs.cast(inputs.command.commandInputs)

        selectInput = inputs.addSelectionInput('profile', 'Profile', 'Select a profile')
        selectInput.addSelectionFilter('Profiles')
        selectInput.setSelectionLimits(1, 1)
        
        selectInput1 = inputs.addSelectionInput('centrePoint', 'Centre', 'Select a centre Point')
        selectInput1.addSelectionFilter('Vertices')
        selectInput1.addSelectionFilter('SketchPoints')
        selectInput1.addSelectionFilter('ConstructionPoints')
        selectInput1.setSelectionLimits(1, 1)
        
        selectInput2 = inputs.addSelectionInput('directionPoint', 'DirectionPoint', 'Select a direction Point')
        selectInput2.addSelectionFilter('Vertices')
        selectInput2.addSelectionFilter('SketchPoints')
        selectInput2.addSelectionFilter('ConstructionPoints')
        selectInput2.setSelectionLimits(1, 1)

        selectInput3 = inputs.addSelectionInput('targetFace', 'TargetFace', 'Select a target Face')
        selectInput3.addSelectionFilter('PlanarFaces')
        selectInput3.setSelectionLimits(1, 1)

        selectInput4 = inputs.addSelectionInput('targetPoint', 'Target Point', 'Select a target point')
        selectInput4.addSelectionFilter('Vertices')
        selectInput4.addSelectionFilter('SketchPoints')
        selectInput4.addSelectionFilter('ConstructionPoints')
        selectInput4.setSelectionLimits(1, 1)
 
        selectInput5 = inputs.addSelectionInput('toFace', 'To Face', 'Select a To face or vertex')
        selectInput5.addSelectionFilter('PlanarFaces')
        selectInput5.addSelectionFilter('Vertices')
        selectInput5.setSelectionLimits(1, 1)

        # Create a text box that will be used to display the results.
        textResult = inputs.addTextBoxCommandInput('textResult', '', '', 2, True)
             
        
        textBox = inputs.addTextBoxCommandInput('TextBox', '', '', 1, True)

        cmd = adsk.core.Command.cast(args.command)
        # Add handlers to this command.
        cmd.execute.add(self.handlers.make_handler(adsk.core.CommandEventHandler, self.onExecute))
#        cmd.selectionEvent.add(self.handlers.make_handler(adsk.core.SelectionEventHandler, self.onFaceSelect))
#        cmd.validateInputs.add(
#            self.handlers.make_handler(adsk.core.ValidateInputsEventHandler, self.onValidate))
        cmd.inputChanged.add(
            self.handlers.make_handler(adsk.core.InputChangedEventHandler, self.onChange))

    def parseInputs(self, inputs):
        inputs = {inp.id: inp for inp in inputs}

        self.profile = inputs['profile'].selection(0).entity
        self.centrePoint = inputs['centrePoint'].selection(0).entity
        self.directionPoint = inputs['directionPoint'].selection(0).entity
        self.targetFromFace = inputs['targetFace'].selection(0).entity
        self.targetPoint = inputs['targetPoint'].selection(0).entity
        self.targetToEntity = inputs['toFace'].selection(0).entity


    def onExecute(self, args):
        start = time.time()

        self.parseInputs(args.firingEvent.sender.commandInputs)
        self.cutDieCommand()      
#        selected = eventArgs.selection
#        selectedEntity = selected.entity

    @property
    def design(self):
        return self.app.activeProduct

    @property
    def rootComp(self):
        return self.design.rootComponent

    @property
    def originPlane(self):
        return self.rootComp.xZConstructionPlane if self.yUp else self.rootComp.xYConstructionPlane

    # The main algorithm
    def cutDieCommand(self):
        self.errorCount = 0
        if not self.design:
            raise RuntimeError('No active Fusion design')
        extrusion = adsk.fusion.ExtrudeFeatures.cast(None)
        extrusion = self.profile.assemblyContext.component.features.extrudeFeatures if self.profile.assemblyContext else self.rootComp.features.extrudeFeatures
        extrusionInput = extrusion.createInput(self.profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation )

        extrusionInput.profile = adsk.fusion.Profile.cast(self.profile)
        fromExtent = adsk.fusion.ToEntityExtentDefinition.create(self.profile.parentSketch.referencePlane, True)
        toExtent = adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByReal(.001))
#        toExtent = adsk.fusion.ToEntityExtentDefinition.create(self.targetToEntity, True)
        extrusionInput.startExtent = fromExtent

        extrusionInput.setOneSideExtent(toExtent, adsk.fusion.ExtentDirections.NegativeExtentDirection)
        
        if self.centrePoint.objectType != adsk.core.Point3D.classType():  #point is provided as a sketchPoint - need to convert to world coordinate space
            self.centrePoint = self.centrePoint.worldGeometry
        
        if self.directionPoint.objectType != adsk.core.Point3D.classType(): #point is provided as a sketchPoint - need to convert to world coordinate space
            self.directionPoint= self.directionPoint.worldGeometry
        
        tool = extrusion.add(extrusionInput)
        startFace = tool.startFaces.item(0)
        transformMatrix = adsk.core.Matrix3D.create()
        tempMatrix = adsk.core.Matrix3D.create()

        
        fromNormal = startFace.evaluator.getNormalAtPoint(startFace.pointOnFace)[1]
        toNormal = self.targetFromFace.evaluator.getNormalAtPoint(self.targetFromFace.pointOnFace)[1]

        fromVector = self.centrePoint.copy().asVector()
        fromVector.scaleBy(-1)
       
        directionVector = self.centrePoint.vectorTo(self.directionPoint)
        
        tempMatrix.translation = fromVector
        transformMatrix.transformBy(tempMatrix) # transform to origin - any rotation around the centrePoint needs to be done at origin

        tempMatrix.setToRotateTo(fromNormal, toNormal) 
        transformMatrix.transformBy(tempMatrix) #rotate to align the planes
        directionVector.transformBy(tempMatrix)
        
        tempMatrix.setToIdentity()  #clear the matrix
        
        if self.targetPoint.objectType != adsk.fusion.BRepVertex.classType() and self.targetPoint.objectType != adsk.fusion.SketchPoint.classType():
            dbutils.messageBox('Choose a vertex')
        
        
        edges = [dbutils.correctedEdgeVector(edge, self.targetPoint ) for edge in self.targetPoint.edges if not fromNormal.isParallelTo(edge.geometry.startPoint.vectorTo(edge.geometry.endPoint))]
        
       
        targetDirectionVector = edges[0].copy()
        targetDirectionVector.normalize()
        edge2Vector = edges[1].copy()
        edge2Vector.normalize()
        targetDirectionVector.add(edge2Vector) #gets the vector exactly half way between the two edges
            
        tempMatrix.setToRotateTo(directionVector, targetDirectionVector) # rotate so direction vector is aligned with half way vector
        transformMatrix.transformBy(tempMatrix)
        directionVector.transformBy(tempMatrix)
            
        
        tempMatrix.setToIdentity()  #clear the matrix
        tempMatrix.translation = self.targetPoint.geometry.asVector()
        transformMatrix.transformBy(tempMatrix) #translate position to final destination

        moveFeats = startFace.body.assemblyContext.component.features.moveFeatures if startFace.assemblyContext else self.rootComp.features.moveFeatures
        bodyCollection = adsk.core.ObjectCollection.create()
        bodyCollection.add(startFace.body)
        moveFeaturesInput = moveFeats.createInput(bodyCollection, transformMatrix)
        moveFeats.add(moveFeaturesInput)
        
        extrudeFeats = startFace.body.assemblyContext.component.features.extrudeFeatures if startFace.assemblyContext else self.rootComp.features.extrudeFeatures
        extrudeFeaturesInput = extrudeFeats.createInput(startFace, adsk.fusion.FeatureOperations.CutFeatureOperation )
        
#        extrudeFeaturesInput.creationOccurrence(self.targetFromFace)
        startExtent = adsk.fusion.ToEntityExtentDefinition.create(self.targetToEntity, False)

        extrudeFeaturesInput.setOneSideExtent(startExtent, adsk.fusion.ExtentDirections.PositiveExtentDirection )
        extrudeFeaturesInput.participantBodies = [self.targetFromFace.body]

        
        extrudeFeats.add(extrudeFeaturesInput) 
        
        tool.bodies.item(0).isVisible = False
        
        
        
                
                

dieTool = DieToolCommand()


def run(context):
    try:
        dieTool.addButton()
    except:
        dbutils.messageBox(traceback.format_exc())


def stop(context):
    try:
        dieTool.removeButton()
    except:
        dbutils.messageBox(traceback.format_exc())
