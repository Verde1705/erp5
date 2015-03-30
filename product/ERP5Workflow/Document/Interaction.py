##############################################################################
#
# Copyright (c) 2006 Nexedi SARL and Contributors. All Rights Reserved.
#               2015 Wenjie Zheng <wenjie.zheng@tiolive.com>
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsability of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# garantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
##############################################################################

from AccessControl import getSecurityManager, ClassSecurityInfo
from Products.ERP5Type import Permissions, PropertySheet
from Products.ERP5Type.XMLObject import XMLObject
from Products.ERP5Type.Globals import PersistentMapping
from Acquisition import aq_inner, aq_parent
from Products.ERP5Type import Globals
from Products.ERP5Type.Permissions import ManagePortal
from Products.DCWorkflow.Guard import Guard
from Products.DCWorkflow.Expression import Expression
from Products.ERP5Workflow.Document.Transition import TRIGGER_WORKFLOW_METHOD

class Interaction(XMLObject):
  """
  An ERP5 Interaction.
  """

  meta_type = 'ERP5 Interaction'
  portal_type = 'Interaction'
  add_permission = Permissions.AddPortalContent
  isPortalContent = 1
  isRADContent = 1

  ### zwj: for security issue
  managed_permission_list = ()
  managed_role = ()
  erp5_permission_roles = {} # { permission: [role] or (role,) }
  manager_bypass = 0
  method_id = ()
  trigger_type = TRIGGER_WORKFLOW_METHOD
  script_name = ()  # Executed before transition
  after_script_name = ()  # Executed after transition
  before_commit_script_name = () #Executed Before Commit Transaction
  activate_script_name = ()  # Executed as activity
  portal_type_filter = None
  portal_type_group_filter = None
  once_per_transaction = False
  temporary_document_disallowed = False
  var_exprs = None  # A mapping.


  # Declarative security
  security = ClassSecurityInfo()
  security.declareObjectProtected(Permissions.AccessContentsInformation)

  # Declarative properties
  property_sheets = (
    PropertySheet.Base,
    PropertySheet.XMLObject,
    PropertySheet.CategoryCore,
    PropertySheet.DublinCore,
    PropertySheet.Interaction,
  )

  def getGuardSummary(self):
    res = None
    if self.guard is not None:
      res = self.guard.getSummary()
    return res

  def getGuard(self):
    if self.guard is None:
      self.generateGuard()
    return self.guard

  def getVarExprText(self, id):
    if not self.var_exprs:
      return ''
    else:
      expr = self.var_exprs.get(id, None)
      if expr is not None:
        return expr.text
      else:
        return ''

  def generateGuard(self):
    if self.trigger_type == TRIGGER_USER_ACTION:
      if self.guard == None:
        self.guard = Guard(permissions=self.getPermissionList(),
                      roles=self.getRoleList(),
                      groups=self.getGroupList(),
                      expr=self.getExpression())

      if self.guard.roles != self.getRoleList():
        self.guard.roles = self.getRoleList()
      elif self.guard.permissions != self.getPermissionList():
        self.guard.permissions = self.getPermissionList()
      elif self.guard.groups != self.getGroupList():
        self.guard.groups = self.getGroupList()
      elif self.guard.expr != self.getExpression():
        self.guard.expr = self.getExpression()

  def execute(self, ob, workflow, result, args=None, kw=None):
    ### zwj: What will be done this part
    ### this part shoud be called in Base.py as transition be called.
    # 1: execute before script;
    # 2: execute after script;
    # 3: Queue before commit script;
    # 4: execute activity script.

    workflow = self.getParent()
    assert self.trigger_type == TRIGGER_WORKFLOW_METHOD

    # Initialize variables
    former_status = workflow._getStatusOf(ob)
    econtext = None
    sci = None

    # Update variables.
    tdef_exprs = self.var_exprs
    if tdef_exprs is None: tdef_exprs = {}
    status = {}
    for vdef in workflow.objectValues(portal_type='Variable'):
      id = vdef.getId()
      if not vdef.for_status:
        continue
      expr = None
      if id in tdef_exprs:
        expr = tdef_exprs[id]
      elif not vdef.update_always and id in former_status:
        # Preserve former value
        value = former_status[id]
      else:
        if vdef.default_expr is not None:
          expr = vdef.default_expr
        else:
          value = vdef.default_value
      if expr is not None:
        # Evaluate an expression.
        if econtext is None:
          # Lazily create the expression context.
          if sci is None:
            sci = StateChangeInfo(
                ob, workflow, former_status, self,
                None, None, None)
          econtext = createExprContext(sci)
        value = expr(econtext)
      status[id] = value

    sci = StateChangeInfo(
          ob, worfklow, former_status, self, None, None, kwargs=kw)
    # Execute the "after" script.
    for script_name in self.after_script_name:
      script = workflow._getOb(script_name)
      # Pass lots of info to the script in a single parameter.
      script(sci)  # May throw an exception

    # Queue the "Before Commit" scripts
    sm = getSecurityManager()
    for script_name in self.before_commit_script_name:
      transaction.get().addBeforeCommitHook(self._before_commit,
                                            (sci, script_name, sm))

    # Execute "activity" scripts
    for script_name in self.activate_script_name:
      workflow.activate(activity='SQLQueue')\
          .activeScript(script_name, ob.getRelativeUrl(),
                        status, self.getId())

  def _before_commit(self, sci, script_name, security_manager):
    # check the object still exists before calling the script
    ob = sci.object
    workflow = self.getParent()
    while ob.isTempObject():
      ob = ob.getParentValue()
    if aq_base(self.unrestrictedTraverse(ob.getPhysicalPath(), None)) is \
       aq_base(ob):
      current_security_manager = getSecurityManager()
      try:
        # Who knows what happened to the authentication context
        # between here and when the interaction was executed... So we
        # need to switch to the security manager as it was back then
        setSecurityManager(security_manager)
        workflow._getOb(script_name)(sci)
      finally:
        setSecurityManager(current_security_manager)

  def activeScript(self, script_name, ob_url, status):
    workflow = self.getParent()
    script = workflow._getOb(script_name)
    ob = self.unrestrictedTraverse(ob_url)
    sci = StateChangeInfo(
                  ob, workflow, status, self, None, None, None)
    script(sci)

  def getVarExprText(self, id):
    if not self.var_exprs:
      return ''
    else:
      expr = self.var_exprs.get(id, None)
      if expr is not None:
        return expr.text
      else:
        return ''

  def getWorkflow(self):
      return aq_parent(aq_inner(aq_parent(aq_inner(self))))