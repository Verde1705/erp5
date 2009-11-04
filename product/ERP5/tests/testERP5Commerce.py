##############################################################################
#
# Copyright (c) 2005 Nexedi SARL and Contributors. All Rights Reserved.
#                     Ivan Tyagov <ivan@nexedi.com>
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

import os
import string
import transaction
import urllib

from Products.ERP5Type.tests.ERP5TypeTestCase import ERP5TypeTestCase
from Products.ERP5Type.tests.utils import FileUpload

SESSION_ID = "12345678"
LANGUAGE_LIST = ('en', 'fr', 'de', 'bg',)
SIMULATE_PAYPAL_SERVER = """
# this script simulate the reponse of paypal
if not 'METHOD' in parameter_dict:
  return {'ACK':'Failure'}

# Step 1 : get a token
if parameter_dict['METHOD'] == 'SetExpressCheckout':
  return {'ACK':'Success',
          'TOKEN':'FOOTOKEN'}

# Step 2 : check if token is good
if parameter_dict['METHOD'] == 'GetExpressCheckoutDetails':
  return {'ACK':'Success',
          'PAYERID':'THEPAYERID'}

# Step 3 : pay
if parameter_dict['METHOD'] == 'DoExpressCheckoutPayment':
  return {'ACK':'Success',
          'PAYERID':'THEPAYERID'}
return {'ACK':'Failure'}
"""


class TestCommerce(ERP5TypeTestCase):
  """
  Todo:
  > Change name of all script, most of them should not be called on a
    SaleOrder.
  > Test SaleOrder_getShoppingCartItemList With include_shipping=True
  > implement Person_getApplicableDiscountList (actually just return None)
  > implement Person_getApplicableTaxList (actually always return a tax of 20%)
  > SaleOrder_externalPaymentHandler is totally empty
  > SaleOrder_finalizeShopping doesnt check if the payment is successful or not
  > Fix proxy for SaleOrder_finalizeShopping anonym and normal user cant use it
  > SaleOrder_getAvailableShippingResourceList have hardcoded
  > SaleOrder_isConsistent the usage must be more generic or rename it
  > SaleOrder_isShippingRequired this script just return 1 ...

  Not tested :
  Person_getApplicableDiscountList
  SaleOrder_externalPaymentHandler
  SaleOrder_isShippingRequired
  WebSection_checkPaypalIdentification
  WebSection_checkoutProcedure
  WebSection_doPaypalPayment
  WebSection_viewCurrentPersonAsWeb
  WebSite_doExpressCheckoutPayment
  WebSite_getExpressCheckoutDetails
  WebSite_getNewPaypalToken
  WebSite_getPaypalOrderParameterDict
  WebSite_getPaypalSecurityParameterDict
  WebSite_getPaypalUrl
  WebSite_setupECommerceWebSite
  Product_getRelatedDescription
  Person_editPersonalInformation
  """

  def getTitle(self):
    return "E-Commerce System"

  def getBusinessTemplateList(self):
    """
      Return the list of required business templates.
    """
    return ('erp5_base',
            'erp5_web',
            'erp5_trade',
            'erp5_pdm',
            'erp5_commerce',)

  def afterSetUp(self):
    uf = self.getPortal().acl_users
    uf._doAddUser('ivan', '', ['Manager'], [])
    uf._doAddUser('customer', '', ['Auditor', 'Author'], [])

    self.login('ivan')

    product_module = self.portal.product_module
    currency_module = self.portal.currency_module
    sale_order_module = self.portal.sale_order_module
    currency_module.manage_permission('Access contents information',
                                     roles=['Anonymous'], acquire=0)
    product_module.manage_permission('Access contents information',
                                     roles=['Anonymous'], acquire=0)
    sale_order_module.manage_permission('Access contents information',
                                     roles=['Anonymous'], acquire=0)

    # create default currency (EUR)
    currency = currency_module.newContent(portal_type='Currency',
                                          id='EUR')
    currency.setTitle('EUR')
    currency.setReference('EUR')
    currency.setShortTitle('€')
    currency.setBaseUnitQuantity(0.01)
    currency.validate()
    currency.publish()

    # create product, set price & currency
    product = product_module.newContent(portal_type='Product', id='1')
    product.setSupplyLinePriceCurrency(currency.getRelativeUrl())
    product.setBasePrice(10.0)
    product.validate()
    product.publish()

    # create second product, set price & currency
    product = product_module.newContent(portal_type='Product', id='2')
    product.setSupplyLinePriceCurrency(currency.getRelativeUrl())
    product.setBasePrice(20.0)
    product.validate()
    product.publish()

    # create shipping which is actually a product
    shipping = product_module.newContent(portal_type='Product',
                                         id='3')
    shipping.setSupplyLinePriceCurrency(currency.getRelativeUrl())
    shipping.setBasePrice(10.0)
    shipping.setProductLine('shipping')
    shipping.validate()
    shipping.publish()

    # validate default order rule
    default_order_rule = self.portal.portal_rules.default_order_rule
    if default_order_rule.getValidationState() != 'validated':
      self.portal.portal_rules.default_order_rule.validate()

    self.website = self.setupWebSite()
    self.website.setProperty('ecommerce_base_currency',
                                            currency.getRelativeUrl())

    self.app.REQUEST.set('session_id', SESSION_ID)
    self.login('ivan')
    transaction.commit()
    self.tic()

  def clearModule(self, module):
    module.manage_delObjects(list(module.objectIds()))
    transaction.commit()
    self.tic()

  def beforeTearDown(self):
    self.clearModule(self.portal.web_site_module)
    self.clearModule(self.portal.product_module)
    self.clearModule(self.portal.sale_order_module)
    self.clearModule(self.portal.currency_module)
    self.portal.portal_caches.clearAllCache()

  def createDefaultOrganisation(self):
    """
      Create Seller organisation
    """
    self.organisation_module = self.portal.getDefaultModule('Organisation')
    if 'seller' not in self.organisation_module.objectIds():
        self.nexedi = self.organisation_module.newContent(title="Seller",
                                                          group='seller',
                                                          role='internal',
                                                          id='seller')

  def createTestUser(self, first_name, last_name, reference, group,
                     destination_project=None, id=None):
    """
      Create a user with the given parameters
    """
    self.person_module = self.getPersonModule()
    if hasattr(self.person_module, id or reference):
      return
    person = self.person_module.newContent(
      first_name=first_name,
      last_name=last_name,
      reference=reference,
      password='secret',
      career_role='internal',
      id=id or reference,
    )

    # Set the assignment
    assignment = person.newContent(portal_type='Assignment')
    assignment.edit(function='',
                    destination_value=getattr(self, 'seller', None),
                    start_date='1972-01-01', stop_date='2999-12-31',
                    group=group, destination_project=destination_project)
    assignment.open()
    transaction.commit()
    self.tic()

    #XXX: Security hack (lucas)
    self.portal.acl_users.zodb_roles.assignRoleToPrincipal('Manager',
                                                           reference)

  def getDefaultProduct(self, id='1'):
    """
      Get default product.
    """
    return self.getPortal().product_module[id]

  def initialiseSupplyLine(self):
    category_list = []
    portal_categories = self.portal.portal_categories
    if hasattr(portal_categories.product_line, 'ldlc'):
      portal_categories.product_line.manage_delObjects(['ldlc'])
    ldlc = portal_categories.product_line.newContent(portal_type='Category',
                                                     id='ldlc',
                                                     title='LDLC')
    laptop = ldlc.newContent(portal_type='Category',
                             id='laptop',
                             title='Laptop')

    netbook = laptop.newContent(portal_type='Category',
                                id='netbook',
                                title='Netbook')

    lcd = ldlc.newContent(portal_type='Category',
                          id='lcd',
                          title='Lcd Screen')
    mp3_player = ldlc.newContent(portal_type='Category',
                                 id='mp3',
                                 title='Mp3 Player')
    category_list.append(laptop)
    category_list.append(netbook)
    category_list.append(lcd)
    category_list.append(mp3_player)

    product_list = []
    for category in category_list:
      for i in range(3):
        title = '%s %s' % (category.getTitle(), i)
        reference = '%s_%s' % (category.getId(), i)
        product = self. portal.product_module.newContent(portal_type="Product",
                                                         title=title,
                                                         reference=reference)
        product_line = category.getRelativeUrl().replace('product_line/', '')
        product.setProductLine(product_line)
        product.setQuantityUnit('unit/piece')
        supply_line = product.newContent(id='default_supply_line',
                                         portal_type='Supply Line')
        supply_line.setBasePrice(10 * (i + 1))
        supply_line.setPricedQuantity(1)
        supply_line.setDefaultResourceValue(product)
        supply_line.setPriceCurrency('currency_module/EUR')
        product_list.append(product)

    for product in product_list:
      product.validate()
      product.publish()

    ups = self.portal.product_module.newContent(portal_type='Product',
                                           title='UPS Shipping : 24h')
    ups.setQuantityUnit('unit/piece')
    supply_line = ups.setProductLine('shipping/UPS24h')
    supply_line = ups.newContent(id='default_supply_line',
                                 portal_type='Supply Line')
    supply_line.setBasePrice(10)
    supply_line.setPricedQuantity(1)
    supply_line.setDefaultResourceValue(product)
    supply_line.setPriceCurrency('currency_module/EUR')
    ups.validate()
    ups.publish()
    transaction.commit()
    self.tic()

  def createUser(self, name, role_list):
    user_folder = self.portal.acl_users
    user_folder._doAddUser(name, 'password', role_list, [])

  def setupWebSite(self, **kw):
    """
      Setup Web Site
    """
    # add supported languages for Localizer
    localizer = self.portal.Localizer
    for language in LANGUAGE_LIST:
      localizer.manage_addLanguage(language=language)

    # create website
    website = getattr(self.portal.web_site_module, 'website', None)
    if website is None:
      website = self.portal.web_site_module.newContent(portal_type='Web Site',
                                                        id='website',
                                                        **kw)
      transaction.commit()
      self.tic()

    website.WebSite_setupECommerceWebSite()
    self.initialiseSupplyLine()
    transaction.commit()
    self.tic()

    self.createDefaultOrganisation()
    self.createTestUser(first_name="Web",
                        last_name='master',
                        reference='webmaster',
                        group=None)

    return website

  def createShoppingCartWithProductListAndShipping(self):
    """
      This method must create a Shopping Cart and add
      some Products and select one Shipping.
    """
    default_product = self.getDefaultProduct()
    self.website.Resource_addToShoppingCart(resource=default_product,
                                             quantity=1)

    shopping_cart = self.portal.SaleOrder_getShoppingCart()
    shipping_list = self.portal.SaleOrder_getAvailableShippingResourceList()
    order_line = getattr(shopping_cart, 'shipping_method', None)
    if order_line is None:
      order_line = shopping_cart.newContent(id='shipping_method',
                                            portal_type='Sale Order Line')
    order_line.setResource(shipping_list[0].getRelativeUrl())
    order_line.setQuantity(1)
    transaction.commit()
    self.tic()

  def test_01_AddResourceToShoppingCart(self):
    """
       Test adding an arbitrary resources to shopping cart.
    """
    default_product = self.getDefaultProduct()

    # set 'session_id' to simulate browser (cookie) environment
    self.app.REQUEST.set('session_id', SESSION_ID)
    self.assertEquals(SESSION_ID, self.website.SaleOrder_getShoppingCartId())

    # check if the shopping cart is empty
    self.assertTrue(self.website.SaleOrder_isShoppingCartEmpty())

    # add product to shopping cart
    self.website.Resource_addToShoppingCart(default_product, 1)

    shoppping_cart_item_list = self.website.SaleOrder_getShoppingCartItemList()
    self.assertEquals(1, len(shoppping_cart_item_list))
    self.assertEquals(1, shoppping_cart_item_list[0].getQuantity())
    self.assertEquals(shoppping_cart_item_list[0].getResource(), \
                                         default_product.getRelativeUrl())
    self.assertFalse(self.website.SaleOrder_isShoppingCartEmpty())

  def test_02_AddSameResourceToShoppingCart(self):
    """
       Test adding same resource to shopping cart.
    """
    default_product = self.getDefaultProduct()

    # add in two steps same product and check that we do not create
    # new Sale Order Line but just increase quantity on existing one
    self.website.Resource_addToShoppingCart(default_product, 1)
    self.website.Resource_addToShoppingCart(default_product, 1)

    shoppping_cart_item_list = self.website.SaleOrder_getShoppingCartItemList()

    self.assertEquals(1, len(shoppping_cart_item_list))
    self.assertEquals(2, shoppping_cart_item_list[0].getQuantity())
    self.assertEquals(shoppping_cart_item_list[0].getResource(), \
                                          default_product.getRelativeUrl())

  def test_03_AddDifferentResourceToShoppingCart(self):
    """
       Test adding different resource to shopping cart.
    """
    default_product = self.getDefaultProduct()
    another_product = self.getDefaultProduct(id='2')

    # add second diff product and check that we create new Sale Order Line
    self.website.Resource_addToShoppingCart(default_product, 1)
    self.website.Resource_addToShoppingCart(default_product, 1)
    self.website.Resource_addToShoppingCart(another_product, 1)
    shoppping_cart_item_list = self.website.SaleOrder_getShoppingCartItemList()
    self.assertEquals(2, len(shoppping_cart_item_list))
    self.assertEquals(2, shoppping_cart_item_list[0].getQuantity())
    self.assertEquals(1, shoppping_cart_item_list[1].getQuantity())
    self.assertEquals(shoppping_cart_item_list[0].getResource(), \
                                          default_product.getRelativeUrl())
    self.assertEquals(shoppping_cart_item_list[1].getResource(), \
                                          another_product.getRelativeUrl())

  def test_04_CalculateTotaShoppingCartPrice(self):
    """
       Test calculation shopping cart's total price.
    """
    default_product = self.getDefaultProduct()
    another_product = self.getDefaultProduct(id='2')
    self.website.Resource_addToShoppingCart(default_product, 1)
    self.website.Resource_addToShoppingCart(default_product, 1)
    self.website.Resource_addToShoppingCart(another_product, 1)

    shopping_cart = self.portal.SaleOrder_getShoppingCart()
    self.assertEquals(40.0, \
         float(self.website.SaleOrder_getShoppingCartTotalPrice()))
    # include taxes (by default it's 20%)
    self.assertEquals(40.0 * 1.20, \
         float(self.website.SaleOrder_getShoppingCartTotalPrice(
                                                        include_shipping=True,
                                                        include_taxes=True)))
    # no shipping selected yet so price should be the same
    self.assertEquals(40.0, \
         float(self.website.SaleOrder_getShoppingCartTotalPrice(
                                         include_shipping=True)))

    # add shipping
    shipping = self.getDefaultProduct('3')
    self.portal.SaleOrder_editShoppingCart(
                        field_my_shipping_method=shipping.getRelativeUrl())

    # test price calculation only with shipping
    self.assertEquals(40.0 + 10.0, \
                float(self.website.SaleOrder_getShoppingCartTotalPrice(
                                                      include_shipping=True)))

    # test price calculation shipping and taxes
    self.assertEquals((40.0 + 10.0) * 1.20, \
                float(self.website.SaleOrder_getShoppingCartTotalPrice(
                                                      include_shipping=True,
                                                      include_taxes=True)))

  def test_05_TestUpdateShoppingCart(self):
    """
       Test update of shopping cart.
    """
    default_product = self.getDefaultProduct()
    another_product = self.getDefaultProduct(id='2')
    shipping = self.getDefaultProduct('3')

    self.website.Resource_addToShoppingCart(default_product, quantity=1)
    self.website.Resource_addToShoppingCart(another_product, quantity=1)

    shopping_cart = self.portal.SaleOrder_getShoppingCart()
    shipping_url = shipping.getRelativeUrl()

    # increase shopping item number and set shipping
    self.portal.SaleOrder_editShoppingCart(field_my_buy_quantity=(2, 1,),
                                      field_my_shipping_method=shipping_url)

    # test price calculation without shipping and without taxes
    self.assertEquals((10.0 * 2 + 20.0 * 1) * 1.0, \
       float(self.website.SaleOrder_getShoppingCartTotalPrice(
                                                    include_shipping=False,
                                                    include_taxes=False)))

    # test price calculation with shipping and without taxes
    self.assertEquals((10.0 * 2 + 20.0 * 1 + 10.0) * 1.0, \
         float(self.website.SaleOrder_getShoppingCartTotalPrice(
                                                    include_shipping=True,
                                                    include_taxes=False)))
    # test price calculation with shipping and with taxes
    self.assertEquals((10.0 * 2 + 20.0 * 1 + 10.0) * 1.20, \
         float(self.website.SaleOrder_getShoppingCartTotalPrice(
                                                    include_shipping=True,
                                                    include_taxes=True)))

    # delete shopping item
    self.portal.SaleOrder_deleteShoppingCartItem('1')
    self.assertEquals(1, \
                      len(self.website.SaleOrder_getShoppingCartItemList()))

    self.portal.SaleOrder_deleteShoppingCartItem('2')
    self.assertEquals(0, \
                      len(self.website.SaleOrder_getShoppingCartItemList()))
    self.assertEquals(0.0, \
                   float(self.website.SaleOrder_getShoppingCartTotalPrice()))

  def test_06_TestClearShoppingCart(self):
    """
       Test clear of shopping cart.
    """
    default_product = self.getDefaultProduct()
    self.createShoppingCartWithProductListAndShipping()
    transaction.commit()
    self.tic()

    shopping_cart = self.website.SaleOrder_getShoppingCart(action='reset')
    self.assertEquals(0, len(self.website.SaleOrder_getShoppingCartItemList()))

  def test_07_SessionIDGeneration(self):
    """
      Test the generation of session id.
    """
    id_string = self.getPortal().Base_generateSessionID()
    self.assertEquals(10, len(id_string))
    for caracter in id_string:
      self.assertTrue(caracter in string.letters)

    id_string = self.getPortal().Base_generateSessionID(max_long=20)
    self.assertEquals(20, len(id_string))

    # XXX : maybe it can be good to forbid this case
    id_string = self.getPortal().Base_generateSessionID(max_long=0)
    self.assertEquals(0, len(id_string))

  def test_08_getApplicableTaxList(self):
    """
      Test the Person_getApplicableTaxList script
    """
    # XXX : actually the script is only in squeleton mode,
    # only return a tax of 20%
    self.assertEquals({'VAT': 20.0},
                          self.getPortal().Person_getApplicableTaxList())

  def test_09_paymentRedirect(self):
    """
      Test the SaleOrder_paymentRedirect script
    """
    default_product = self.getDefaultProduct()
    self.website.Resource_addToShoppingCart(default_product, quantity=1)
    transaction.commit()
    self.tic()

    # the confirmation should not be possible if the user is not logged
    self.logout()
    self.assertEquals(1, len(self.website.SaleOrder_getShoppingCartItemList()))
    self.portal.SaleOrder_paymentRedirect()
    self.assertTrue(urllib.quote("You need to create an account to " \
                              "continue. If you already have please login.") in
                    self.app.REQUEST.RESPONSE.getHeader('location'))

    # but it should work if the user is authenticated
    self.login('customer')
    self.portal.SaleOrder_paymentRedirect()
    self.assertTrue(urllib.quote("SaleOrder_viewConfirmAsWeb") in
                    self.app.REQUEST.RESPONSE.getHeader('location'))

  def test_10_deleteShoppingCartItem(self):
    """
      Test the SaleOrder_deleteShoppingCartItem script
    """
    default_product = self.getDefaultProduct()
    self.website.Resource_addToShoppingCart(default_product, quantity=1)
    self.assertEquals(1, len(self.website.SaleOrder_getShoppingCartItemList()))

    # Trying to remove
    self.portal.SaleOrder_deleteShoppingCartItem()
    self.assertTrue(urllib.quote("Please select an item.") in
                               self.app.REQUEST.RESPONSE.getHeader('location'))

    # Check if the item still into the Shopping Cart
    self.assertEquals(1, len(self.website.SaleOrder_getShoppingCartItemList()))

    # Remove the product from the Shopping Cart
    product_id = default_product.getId()
    self.portal.SaleOrder_deleteShoppingCartItem(
                                          field_my_order_line_id=product_id)

    # Check if the Product have been removed sucessfully
    self.assertTrue(
              urllib.quote("Successfully removed from shopping cart.") in
                 self.app.REQUEST.RESPONSE.getHeader('location'))

    # Check if the Shopping Cart is empty
    self.assertEquals(0, len(self.website.SaleOrder_getShoppingCartItemList()))

  def test_11_finalizeShopping(self):
    """
      Test the SaleOrder_finalizeShopping script
    """
    self.login('webmaster')
    self.website.Resource_addToShoppingCart(self.getDefaultProduct(),
                                           quantity=1)
    self.website.Resource_addToShoppingCart(self.getDefaultProduct('2'),
                                           quantity=1)
    transaction.commit()
    self.tic()

    self.assertEquals(2, len(self.website.SaleOrder_getShoppingCartItemList()))
    self.assertEquals(0, len(self.portal.sale_order_module.contentValues()))

    self.website.SaleOrder_finalizeShopping()
    transaction.commit()
    self.tic()

    sale_order_object_list = self.portal.sale_order_module.contentValues()
    self.assertEquals(1, len(sale_order_object_list))
    self.assertEquals(2, len(sale_order_object_list[0].contentValues()))
    self.assertEquals(0, len(self.website.SaleOrder_getShoppingCartItemList()))

  def test_12_getAvailableShippingResourceList(self):
    """
      Test the SaleOrder_getAvailableShippingResourceList script
    """
    default_product = self.getDefaultProduct()
    product_line = self.portal.portal_categories.product_line
    shipping_url = product_line.shipping.getRelativeUrl()
    self.portal.product_module.newContent(portal_type='Product',
                                          title='shipping',
                                          product_line=shipping_url)
    transaction.commit()
    self.tic()
    self.assertEquals(2,
               len(self.portal.SaleOrder_getAvailableShippingResourceList()))

  def test_13_getFormatedData(self):
    """
      Test the datas formating scripts
    """
    sale_order = self.portal.sale_order_module.newContent(
                                                portal_type="Sale Order")
    sale_order_line = sale_order.newContent(portal_type="Sale Order Line",
                                            quantity="2",
                                            price="10")

    self.assertEqual(
          sale_order.getCreationDate().strftime('%a, %d %b %Y %H:%M %p'),
                    sale_order.SaleOrder_getFormattedCreationDate())
    self.assertEqual('%s %s' % ('20.0', sale_order.getPriceCurrencyTitle()),
                           sale_order.SaleOrder_getFormattedTotalPrice())

  def test_14_getSelectedShippingResource(self):
    """
      Test the SaleOrder_getSelectedShippingResource script
    """
    default_product = self.getDefaultProduct()
    self.website.Resource_addToShoppingCart(default_product, 1)
    shopping_cart = self.portal.SaleOrder_getShoppingCart()
    shipping_list = self.portal.SaleOrder_getAvailableShippingResourceList()

    order_line = getattr(shopping_cart, 'shipping_method', None)
    if order_line is None:
      order_line = shopping_cart.newContent(id='shipping_method',
                                            portal_type='Sale Order Line')

    order_line.setResource(shipping_list[0].getRelativeUrl())
    order_line.setQuantity(1)
    self.assertEquals(shipping_list[0].getRelativeUrl(),
                      self.portal.SaleOrder_getSelectedShippingResource())

  def test_15_getShoppingCartDefaultCurrency(self):
    """
      Testing the scripts:
      - WebSite_getShoppingCartDefaultCurrency
      - WebSite_getShoppingCartDefaultCurrencyCode
      - WebSite_getShoppingCartDefaultCurrencySymbol
    """
    currency = self.portal.restrictedTraverse('currency_module/EUR')
    self.assertEquals(currency,
                      self.website.WebSite_getShoppingCartDefaultCurrency())

    self.assertEquals(currency.getReference(),
                   self.website.WebSite_getShoppingCartDefaultCurrencyCode())

    self.assertEquals(currency.getShortTitle(),
                 self.website.WebSite_getShoppingCartDefaultCurrencySymbol())

  def test_16_simulatePaypalPayment(self):
    """
      Test all the scripts related to paypal
    """
    # create new python script to replace the external method
    custom_skin = self.portal.portal_skins.custom
    method_id = 'WebSection_submitPaypalNVPRequest'
    if method_id in custom_skin.objectIds():
      custom_skin.manage_delObjects([method_id])
    custom_skin.manage_addProduct['PythonScripts']\
                   .manage_addPythonScript(id=method_id)

    script = custom_skin[method_id]
    script.ZPythonScript_edit('parameter_dict, nvp_url',
                                                  SIMULATE_PAYPAL_SERVER)

    self.portal.changeSkin('View')

    #1 initialise a website
    self.website.setProperty('ecommerce_paypal_username', 'user')
    self.website.setProperty('ecommerce_paypal_password', 'pass')
    self.website.setProperty('ecommerce_paypal_signature', 'signature')

    #2 login and activate a cart
    self.login('webmaster')
    request = self.app.REQUEST
    request.set('session_id', SESSION_ID)

    #3 add a product in the cart
    self.createShoppingCartWithProductListAndShipping()

    #4 : paypal step 1 : get a new token
    token = self.website.checkout.WebSection_getNewPaypalToken()
    self.assertNotEquals(token, None)

    #5 : paypal step 2 : go to paypal and confirm this token
    # PayerID is normaly set in the request when paypal
    # redirect to the instance
    request.set('PayerID', 'THEPAYERID')

    #6 : paypal step 3 : check if this token is confirmed by paypal
    error = self.website.WebSection_checkPaypalIdentification()
    self.assertEquals(error, None)
    self.assertTrue('/checkout' in request.RESPONSE.getHeader('location'))

    #7 : paypal step 4 : validate the payment
    self.assertEquals(1,
                       len(self.website.SaleOrder_getShoppingCartItemList()))
    self.assertEquals(0, len(self.portal.sale_order_module.contentValues()))

    self.website.WebSection_doPaypalPayment(token=token)
    transaction.commit()
    self.tic()

    #8 check if sale order created
    self.assertEquals(0, len(self.website.SaleOrder_getShoppingCartItemList()))
    self.assertEquals(1, len(self.portal.sale_order_module.contentValues()))

    custom_skin.manage_delObjects([method_id])

  def test_17_getProductListFromWebSection(self):
    """
      Test the  WebSection_getProductList script.
    """
    laptop_product = self.getDefaultProduct(id='1')
    laptop_product.setProductLine('ldlc/laptop')
    netbook_product = self.getDefaultProduct(id='2')
    netbook_product.setProductLine('ldlc/laptop')

    self.website.WebSection_generateSectionFromCategory(
                                              category='product_line/ldlc',
                                              section_id='product_section',
                                              depth=2)
    transaction.commit()
    self.tic()

    self.assertEquals(14,
             len(self.website.product_section.WebSection_getProductList()))
    self.assertEquals(8,
         len(self.website.product_section.laptop.WebSection_getProductList()))

    netbook_section = self.website.product_section.laptop.netbook
    self.assertEquals(3, len(netbook_section.WebSection_getProductList()))

  def test_18_editShoppingCardWithABlankShippingMethod(self):
    """
      This test must make sure that you can edit the shopping cart selecting a
      blank shipping method and it will not break.
    """
    default_product = self.getDefaultProduct()
    self.website.Resource_addToShoppingCart(default_product, 1)

    shopping_cart = self.website.SaleOrder_getShoppingCart()
    self.assertFalse(hasattr(shopping_cart, 'shipping_method'))

    self.portal.SaleOrder_editShoppingCart(field_my_shipping_method='')
    self.portal.SaleOrder_editShoppingCart(field_my_shipping_method=None)

    # add shipping
    shipping = self.getDefaultProduct('3')
    self.portal.SaleOrder_editShoppingCart(
                          field_my_shipping_method=shipping.getRelativeUrl())

    self.assertTrue(hasattr(shopping_cart, 'shipping_method'))

  def test_19_editShoppingCardWithShippingMethodWithoutPrice(self):
    """
      This test must make sure that you can not edit the shopping cart
      selecting a shipping method without price.
    """
    default_product = self.getDefaultProduct(id='1')
    self.website.Resource_addToShoppingCart(default_product, 1)
    shopping_cart = self.website.SaleOrder_getShoppingCart()

    # add shipping
    shipping = self.getDefaultProduct('3')
    shipping.setBasePrice(None)
    self.website.SaleOrder_editShoppingCart(
                     field_my_shipping_method=shipping.getRelativeUrl())

    self.assertEquals(10.0, \
            float(self.website.SaleOrder_getShoppingCartTotalPrice(
                                                    include_shipping=True)))

  def test_20_getProductListFromWebSite(self):
    """
      Test the  WebSite_getProductList script.
    """
    self.assertEquals(5, len(self.website.WebSite_getProductList()))
    self.assertEquals(16,
               len(self.website.WebSite_getProductList(limit=1000)))

  def test_21_AddResourceToShoppingCartWithAnonymousUser(self):
    """
      Test adding an arbitrary resources to shopping cart with Anonymous user.
    """
    # anonymous user
    self.logout()
    self.createShoppingCartWithProductListAndShipping()
    shoppping_cart_item_list = self.website.SaleOrder_getShoppingCartItemList()
    self.assertEquals(1, len(shoppping_cart_item_list))

  def test_22_createShoppingCartWithAnonymousAndLogin(self):
    """
      Test adding an arbitrary resources to shopping cart with Anonymous user
      then create a new user, login and check if the Shopping Cart still the
      same.
    """
    # anonymous user
    self.logout()
    self.createShoppingCartWithProductListAndShipping()
    kw = dict(reference='toto',
              first_name='Toto',
              last_name='Test',
              default_email_text='test@test.com',
              password='secret',
              password_confirm='secret')
    for key, item in kw.items():
      self.app.REQUEST.set('field_your_%s' % key, item)
    self.website.WebSite_createWebSiteAccount('WebSite_viewRegistrationDialog')
    transaction.commit()
    self.tic()

    self.login('toto')
    self.portal.SaleOrder_paymentRedirect()
    self.assertTrue(urllib.quote("SaleOrder_viewConfirmAsWeb") in
                    self.app.REQUEST.RESPONSE.getHeader('location'))

  def test_23_getShoppingCartCustomer(self):
    """
      It must test SaleOrder_getShoppingCartCustomer script
      for a given Authenticated Member it should return the person value.
    """
    self.logout()
    person_object = self.website.SaleOrder_getShoppingCartCustomer()
    self.assertEquals(person_object, None)

    self.login('webmaster')
    person_object = self.website.SaleOrder_getShoppingCartCustomer()
    self.assertNotEquals(person_object, None)
    self.assertEquals(person_object.getReference(), 'webmaster')

  def test_24_getImageDataWithAnonymousUser(self):
    """
      Anonymous user must be able to get product image.
    """
    product = self.getDefaultProduct()
    file_upload = FileUpload(os.path.join(os.path.dirname(__file__),
                          'test_data', 'images', 'erp5_logo_small.png'), 'rb')
    product.edit(default_image_file=file_upload)
    transaction.get()
    self.tic()

    self.logout()
    product = self.getDefaultProduct()
    self.assertTrue(product.getDefaultImageValue().getData()
                                                 not in ('', None))

  def test_25_getSaleOrderModuleAbsoluteUrlWithAnonymousUser(self):
    """
      Anonymous User must have permission access Sale Order Module contents
      information.
    """
    self.logout()
    self.assertNotEquals(self.website.sale_order_module.absolute_url(), None)

  def test_26_getShoppingCartDefaultCurrencyWithAnonymousUser(self):
    """
      Anonymous User must have persmission to access Currency Module contents
      information and Published Currency objects.
      Testing the scripts:
      - WebSite_getShoppingCartDefaultCurrency
      - WebSite_getShoppingCartDefaultCurrencyCode
      - WebSite_getShoppingCartDefaultCurrencySymbol
    """
    self.logout()
    currency_url = self.website.getLayoutProperty('ecommerce_base_currency')
    currency_object = self.portal.restrictedTraverse(currency_url)
    self.assertEquals(currency_object,
                      self.website.WebSite_getShoppingCartDefaultCurrency())

    self.assertEquals(currency_object.getReference(),
                   self.website.WebSite_getShoppingCartDefaultCurrencyCode())

    self.assertEquals(currency_object.getShortTitle(),
                 self.website.WebSite_getShoppingCartDefaultCurrencySymbol())

  def test_27_ResourceGetShopUrl(self):
    """
      For a given Resource the Python Script (Resource_getShopUrl)
      should return the Shopping Url.
    """
    product = self.getDefaultProduct()
    self.assertEquals(product.Resource_getShopUrl(),
                 '%s/%s' % (product.getRelativeUrl(), 'Resource_viewAsShop'))

  def test_28_finalizeShoppingWithComment(self):
    """
      Testing if the comment added during the checkout will be set on the sale
      order object generated.
    """
    self.login('webmaster')
    comment = 'TESTING COMMENT'
    self.website.Resource_addToShoppingCart(self.getDefaultProduct(),
                                           quantity=1)

    self.website.SaleOrder_paymentRedirect(field_my_comment=comment)
    self.website.SaleOrder_finalizeShopping()
    transaction.commit()
    self.tic()

    sale_order_object_list = self.portal.sale_order_module.contentValues()
    self.assertEquals(comment, sale_order_object_list[0].getComment())

import unittest


def test_suite():
  suite = unittest.TestSuite()
  suite.addTest(unittest.makeSuite(TestCommerce))
  return suite
