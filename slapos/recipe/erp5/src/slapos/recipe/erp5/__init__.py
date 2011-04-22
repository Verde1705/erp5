##############################################################################
#
# Copyright (c) 2010 Vifib SARL and Contributors. All Rights Reserved.
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsibility of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# guarantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
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
from slapos.lib.recipe.BaseSlapRecipe import BaseSlapRecipe
import binascii
import os
import pkg_resources
import hashlib
import sys
import zc.buildout
import zc.recipe.egg

# Taken from Zope2 egg
def write_inituser(fn, user, password):
  fp = open(fn, "w")
  pw = binascii.b2a_base64(hashlib.sha1(password).digest())[:-1]
  fp.write('%s:{SHA}%s\n' % (user, pw))
  fp.close()
  os.chmod(fn, 0600)


class Recipe(BaseSlapRecipe):
  def getTemplateFilename(self, template_name):
    return pkg_resources.resource_filename(__name__,
        'template/%s' % template_name)

  site_id = 'erp5'

  def _install(self):
    self.path_list = []
    self.requirements, self.ws = self.egg.working_set([__name__])
    # self.cron_d is a directory, where cron jobs can be registered
    self.cron_d = self.installCrond()
    self.logrotate_d = self.installLogrotate()
    ca_conf = self.installCertificateAuthority()
    memcached_conf = self.installMemcached(ip=self.getLocalIPv4Address(),
        port=11000)
    kumo_conf = self.installKumo(self.getLocalIPv4Address())
    conversion_server_conf = self.installConversionServer(
        self.getLocalIPv4Address(), 23000, 23060)
    mysql_conf = self.installMysqlServer(self.getLocalIPv4Address(), 45678)
    user, password = self.installERP5()
    zodb_dir = os.path.join(self.data_root_directory, 'zodb')
    self._createDirectory(zodb_dir)
    zodb_root_path = os.path.join(zodb_dir, 'root.fs')
    zope_access = self.installZope(ip=self.getLocalIPv4Address(),
          port=12000 + 1, name='zope_%s' % 1,
          zodb_root_path=zodb_root_path)
    apache_conf = dict(
        apache_login=self.installLoginApache(ip=self.getGlobalIPv6Address(),
          port=13000, backend=zope_access, key=ca_conf['login_key'],
          certificate=ca_conf['login_certificate']))
    self.installERP5Site(user, password, zope_access, mysql_conf, 
             conversion_server_conf, memcached_conf, kumo_conf, self.site_id)
    self.installTestRunner(ca_conf, mysql_conf, conversion_server_conf,
                           memcached_conf, kumo_conf)
    self.installTestSuiteRunner(ca_conf, mysql_conf, conversion_server_conf,
                           memcached_conf, kumo_conf)
    self.linkBinary()
    self.setConnectionDict(dict(
      site_url=apache_conf['apache_login'],
      site_user=user,
      site_password=password,
      memcached_url=memcached_conf['memcached_url'],
      kumo_url=kumo_conf['kumo_address']
    ))
    return self.path_list

  def installLogrotate(self):
    """Installs logortate main configuration file and registers its to cron"""
    logrotate_d = os.path.abspath(os.path.join(self.etc_directory,
      'logrotate.d'))
    self._createDirectory(logrotate_d)
    logrotate_conf = self.createConfigurationFile("logrotate.conf",
        "include %s" % logrotate_d)
    logrotate_cron = os.path.join(self.cron_d, 'logrotate')
    state_file = os.path.join(self.data_root_directory, 'logrotate.status')
    open(logrotate_cron, 'w').write('0 0 * * * %s -s %s %s' %
        (self.options['logrotate_binary'], state_file, logrotate_conf))
    self.path_list.extend([logrotate_d, logrotate_conf, logrotate_cron])
    return logrotate_d

  def registerLogRotation(self, name, log_file_list, postrotate_script):
    """Register new log rotation requirement"""
    open(os.path.join(self.logrotate_d, name), 'w').write(
        self.substituteTemplate(self.getTemplateFilename(
          'logrotate_entry.in'),
          dict(file_list=['"'+q+'"' for q in log_file_list],
            postrotate=postrotate_script)))

  def linkBinary(self):
    """Links binaries to instance's bin directory for easier exposal"""
    for linkline in self.options.get('link_binary_list', '').splitlines():
      if not linkline:
        continue
      target = linkline.split()
      if len(target) == 1:
        target = target[0]
        path, linkname = os.path.split(target)
      else:
        linkname = target[1]
        target = target[0]
      link = os.path.join(self.bin_directory, linkname)
      if os.path.lexists(link):
        if not os.path.islink(link):
          raise zc.buildout.UserError(
              'Target link already %r exists but it is not link' % link)
        os.unlink(link)
      os.symlink(target, link)
      self.logger.debug('Created link %r -> %r' % (link, target))
      self.path_list.append(link)

  def installKumo(self, ip, kumo_manager_port=13101, kumo_server_port=13201,
      kumo_server_listen_port=13202, kumo_gateway_port=13301):
    config = dict(
      kumo_gateway_binary=self.options['kumo_gateway_binary'],
      kumo_gateway_ip=ip,
      kumo_gateway_log=os.path.join(self.log_directory, "kumo-gateway.log"),
      kumo_manager_binary=self.options['kumo_manager_binary'],
      kumo_manager_ip=ip,
      kumo_manager_log=os.path.join(self.log_directory, "kumo-manager.log"),
      kumo_server_binary=self.options['kumo_server_binary'],
      kumo_server_ip=ip,
      kumo_server_log=os.path.join(self.log_directory, "kumo-server.log"),
      kumo_server_storage=os.path.join(self.data_root_directory, "kumodb.tch"),
      kumo_manager_port=kumo_manager_port,
      kumo_server_port=kumo_server_port,
      kumo_server_listen_port=kumo_server_listen_port,
      kumo_gateway_port=kumo_gateway_port
    )

    self.path_list.append(self.createRunningWrapper('kumo_gateway',
      self.substituteTemplate(self.getTemplateFilename('kumo_gateway.in'),
        config)))

    self.path_list.append(self.createRunningWrapper('kumo_manager',
      self.substituteTemplate(self.getTemplateFilename('kumo_manager.in'),
        config)))

    self.path_list.append(self.createRunningWrapper('kumo_server',
      self.substituteTemplate(self.getTemplateFilename('kumo_server.in'),
        config)))

    return dict(
      kumo_address = '%s:%s' % (config['kumo_gateway_ip'],
        config['kumo_gateway_port']),
      kumo_gateway_ip=config['kumo_gateway_ip'],
      kumo_gateway_port=config['kumo_gateway_port'],
    )

  def installMemcached(self, ip, port):
    config = dict(
        memcached_binary=self.options['memcached_binary'],
        memcached_ip=ip,
        memcached_port=port,
    )
    self.path_list.append(self.createRunningWrapper('memcached',
      self.substituteTemplate(self.getTemplateFilename('memcached.in'),
        config)))
    return dict(memcached_url='%s:%s' %
        (config['memcached_ip'], config['memcached_port']),
        memcached_ip=config['memcached_ip'],
        memcached_port=config['memcached_ip'])

  def installTestRunner(self, ca_conf, mysql_conf, conversion_server_conf,
                        memcached_conf, kumo_conf):
    """Installs bin/runUnitTest executable to run all tests using
       bin/runUnitTest"""
    testinstance = self.createDataDirectory('testinstance')
    # workaround wrong assumptions of ERP5Type.tests.runUnitTest about
    # directory existence
    unit_test = os.path.join(testinstance, 'unit_test')
    if not os.path.isdir(unit_test):
      os.mkdir(unit_test)
    runUnitTest = zc.buildout.easy_install.scripts([
      ('runUnitTest', __name__ + '.testrunner', 'runUnitTest')],
      self.ws, sys.executable, self.bin_directory, arguments=[dict(
        instance_home=testinstance,
        prepend_path=self.bin_directory,
        openssl_binary=self.options['openssl_binary'],
        test_ca_path=ca_conf['certificate_authority_path'],
        call_list=[self.options['runUnitTest_binary'],
          '--erp5_sql_connection_string', '%(mysql_test_database)s@%'
          '(ip)s:%(tcp_port)s %(mysql_test_user)s '
          '%(mysql_test_password)s' % mysql_conf,
          '--conversion_server_hostname=%(conversion_server_ip)s' % \
                                                         conversion_server_conf,
          '--conversion_server_port=%(conversion_server_port)s' % \
                                                         conversion_server_conf,
          '--volatile_memcached_server_hostname=%(memcached_ip)s' % memcached_conf,
          '--volatile_memcached_server_port=%(memcached_port)s' % memcached_conf,
          '--persistent_memcached_server_hostname=%(kumo_gateway_ip)s' % kumo_conf,
          '--persistent_memcached_server_port=%(kumo_gateway_port)s' % kumo_conf,
      ]
        )])[0]
    self.path_list.append(runUnitTest)

  def installTestSuiteRunner(self, ca_conf, mysql_conf, conversion_server_conf,
                        memcached_conf, kumo_conf):
    """Installs bin/runTestSuite executable to run all tests using
       bin/runUnitTest"""
    testinstance = self.createDataDirectory('test_suite_instance')
    # workaround wrong assumptions of ERP5Type.tests.runUnitTest about
    # directory existence
    unit_test = os.path.join(testinstance, 'unit_test')
    if not os.path.isdir(unit_test):
      os.mkdir(unit_test)
    connection_string_list = []
    for test_database, test_user, test_password in \
        mysql_conf['mysql_parallel_test_dict']:
      connection_string_list.append(
          '%s@%s:%s %s %s' % (test_database, mysql_conf['ip'],
                              mysql_conf['tcp_port'], test_user, test_password))
    command = zc.buildout.easy_install.scripts([
      ('runTestSuite', __name__ + '.test_suite_runner', 'runTestSuite')],
      self.ws, sys.executable, self.bin_directory, arguments=[dict(
        instance_home=testinstance,
        prepend_path=self.bin_directory,
        openssl_binary=self.options['openssl_binary'],
        test_ca_path=ca_conf['certificate_authority_path'],
        call_list=[self.options['runTestSuite_binary'],
          '--db_list', ', '.join(connection_string_list),
          '--conversion_server_hostname=%(conversion_server_ip)s' % \
                                                         conversion_server_conf,
          '--conversion_server_port=%(conversion_server_port)s' % \
                                                         conversion_server_conf,
          '--volatile_memcached_server_hostname=%(memcached_ip)s' % memcached_conf,
          '--volatile_memcached_server_port=%(memcached_port)s' % memcached_conf,
          '--persistent_memcached_server_hostname=%(kumo_gateway_ip)s' % kumo_conf,
          '--persistent_memcached_server_port=%(kumo_gateway_port)s' % kumo_conf,
      ]
        )])[0]
    self.path_list.append(command)

  def installCrond(self):
    timestamps = self.createDataDirectory('cronstamps')
    cron_d = os.path.join(self.etc_directory, 'cron.d')
    crontabs = os.path.join(self.etc_directory, 'crontabs')
    logfile = os.path.join(self.log_directory, 'cron.log')
    self._createDirectory(cron_d)
    self._createDirectory(crontabs)
    wrapper = zc.buildout.easy_install.scripts([('crond',
      __name__ + '.execute', 'execute')], self.ws, sys.executable,
      self.wrapper_directory, arguments=[
        self.options['dcrond_binary'].strip(), '-s', cron_d, '-c', crontabs,
        '-t', timestamps, '-L', logfile, '-f', '-l', '10']
      )[0]
    self.path_list.append(wrapper)
    return cron_d

  def installCertificateAuthority(self, ca_country_code='XX',
      ca_email='xx@example.com', ca_state='State', ca_city='City',
      ca_company='Company'):
    config = dict(
      ca_dir=os.path.join(self.data_root_directory, 'ca'))
    login_key = os.path.join(config['ca_dir'], 'private', 'login.key')
    login_certificate = os.path.join(config['ca_dir'], 'certs', 'login.crt')
    key_auth_key = os.path.join(config['ca_dir'], 'private', 'keyauth.key')
    key_auth_certificate = os.path.join(config['ca_dir'], 'certs',
        'keyauth.crt')

    config.update(
      ca_certificate=os.path.join(config['ca_dir'], 'cacert.pem'),
      ca_key=os.path.join(config['ca_dir'], 'private', 'cakey.pem'),
      ca_crl=os.path.join(config['ca_dir'], 'crl'),
      login_key=login_key,
      login_certificate=login_certificate,
      key_auth_key=key_auth_key,
      key_auth_certificate=key_auth_certificate,
    )
    self._createDirectory(config['ca_dir'])
    for d in ['certs', 'crl', 'newcerts', 'private']:
      self._createDirectory(os.path.join(config['ca_dir'], d))
    for f in ['crlnumber', 'serial']:
      if not os.path.exists(os.path.join(config['ca_dir'], f)):
        open(os.path.join(config['ca_dir'], f), 'w').write('01')
    if not os.path.exists(os.path.join(config['ca_dir'], 'index.txt')):
      open(os.path.join(config['ca_dir'], 'index.txt'), 'w').write('')
    config['openssl_configuration'] = os.path.join(config['ca_dir'],
        'openssl.cnf')
    config.update(
        working_directory=config['ca_dir'],
        country_code=ca_country_code,
        state=ca_state,
        city=ca_city,
        company=ca_company,
        email_address=ca_email,
    )
    self._writeFile(config['openssl_configuration'],
        pkg_resources.resource_string(__name__,
          'template/openssl.cnf.ca.in') % config)
    self.path_list.extend(zc.buildout.easy_install.scripts([
      ('certificate_authority',
        __name__ + '.certificate_authority', 'runCertificateAuthority')],
        self.ws, sys.executable, self.wrapper_directory, arguments=[dict(
          openssl_configuration=config['openssl_configuration'],
          openssl_binary=self.options['openssl_binary'],
          ca_certificate=os.path.join(config['ca_dir'], 'cacert.pem'),
          ca_key=os.path.join(config['ca_dir'], 'private', 'cakey.pem'),
          ca_crl=os.path.join(config['ca_dir'], 'crl'),
          login_key=os.path.join(config['ca_dir'], 'private', 'login.key'),
          login_certificate=login_certificate,
          key_auth_key=key_auth_key,
          key_auth_certificate=key_auth_certificate,
          )]))
    return dict(
      login_key=login_key, login_certificate=login_certificate,
      key_auth_key=key_auth_key, key_auth_certificate=key_auth_certificate,
      ca_certificate=os.path.join(config['ca_dir'], 'cacert.pem'),
      ca_crl=os.path.join(config['ca_dir'], 'crl'),
      certificate_authority_path=config['ca_dir']
    )

  def installConversionServer(self, ip, port, openoffice_port):
    name = 'conversion_server'
    working_directory = self.createDataDirectory(name)
    conversion_server_dict = dict(
      working_path=working_directory,
      uno_path=self.options['ooo_uno_path'],
      office_binary_path=self.options['ooo_binary_path'],
      ip=ip,
      port=port,
      openoffice_port=openoffice_port,
    )
    for env_line in self.options['environment'].splitlines():
      env_line = env_line.strip()
      if not env_line:
        continue
      if '=' in env_line:
        env_key, env_value = env_line.split('=')
        conversion_server_dict[env_key.strip()] = env_value.strip()
      else:
        raise zc.buildout.UserError('Line %r in environment parameter is '
            'incorrect' % env_line)
    config_file = self.createConfigurationFile(name + '.cfg',
        self.substituteTemplate(self.getTemplateFilename('cloudooo.cfg.in'),
          conversion_server_dict))
    self.path_list.append(config_file)
    self.path_list.extend(zc.buildout.easy_install.scripts([(name,
      __name__ + '.execute', 'execute_with_signal_translation')], self.ws,
      sys.executable, self.wrapper_directory,
      arguments=[self.options['ooo_paster'].strip(), 'serve', config_file]))
    return {
      name + '_port': conversion_server_dict['port'],
      name + '_ip': conversion_server_dict['ip']
      }

  def installHaproxy(self, ip, port, name, server_check_path, url_list):
    server_template = """  server %(name)s %(address)s cookie %(name)s check inter 20s rise 2 fall 4"""
    config = dict(name=name, ip=ip, port=port,
        server_check_path=server_check_path,)
    i = 1
    server_list = []
    for url in url_list:
      server_list.append(server_template % dict(name='%s_%s' % (name, i),
        address=url))
      i += 1
    config['server_text'] = '\n'.join(server_list)
    haproxy_conf_path = self.createConfigurationFile('haproxy_%s.cfg' % name,
      self.substituteTemplate(self.getTemplateFilename('haproxy.cfg.in'),
        config))
    self.path_list.append(haproxy_conf_path)
    wrapper = zc.buildout.easy_install.scripts([('haproxy_%s' % name,
      __name__ + '.execute', 'execute')], self.ws, sys.executable,
      self.wrapper_directory, arguments=[
        self.options['haproxy_binary'].strip(), '-f', haproxy_conf_path]
      )[0]
    self.path_list.append(wrapper)
    return '%s:%s' % (ip, port)

  def installERP5(self):
    """
    All zope have to share file created by portal_classes
    (until everything is integrated into the ZODB).
    So, do not request zope instance and create multiple in the same partition.
    """
    # Create instance directories
    self.erp5_directory = self.createDataDirectory('erp5shared')
    # Create init user
    password = self.generatePassword()
    # XXX Unhardcoded me please
    user = 'zope'
    write_inituser(os.path.join(self.erp5_directory, "inituser"),
        user, password)

    self._createDirectory(self.erp5_directory)
    for directory in (
      'Constraint',
      'Document',
      'Extensions',
      'PropertySheet',
      'import',
      'lib',
      'tests',
      'Products',
      ):
      self._createDirectory(os.path.join(self.erp5_directory, directory))
    return user, password

  def installERP5Site(self, user, password, zope_access, mysql_conf,
          conversion_server_conf=None, memcached_conf=None, kumo_conf=None, erp5_site_id='erp5'):
    """ Create a script controlled by supervisor, which creates a erp5
    site on current available zope and mysql environment"""
    conversion_server = None
    if conversion_server_conf is not None:
      conversion_server = "%s:%s" % (conversion_server_conf['conversion_server_ip'],
             conversion_server_conf['conversion_server_port'])
    if memcached_conf is None:
      memcached_conf = {}
    if kumo_conf is None:
      kumo_conf = {}
    # XXX Conversion server and memcache server coordinates are not relevant
    # for pure site creation.
    https_connection_url = "http://%s:%s@%s/" % (user, password, zope_access)
    mysql_connection_string = "%(mysql_database)s@%(ip)s:%(tcp_port)s %(mysql_user)s %(mysql_password)s" % mysql_conf

    # XXX URL list vs. repository + list of bt5 names?
    bt5_list = self.parameter_dict.get("bt5_list", "").split()
    bt5_repository_list = self.parameter_dict.get("bt5_repository_list", "").split()

    self.path_list.extend(zc.buildout.easy_install.scripts([('erp5_update',
            __name__ + '.erp5', 'updateERP5')], self.ws,
                  sys.executable, self.wrapper_directory,
                  arguments=[erp5_site_id,
                             mysql_connection_string,
                             https_connection_url,
                             memcached_conf.get('memcached_url'),
                             conversion_server,
                             kumo_conf.get("kumo_address"),
                             bt5_list,
                             bt5_repository_list]))
    return []

  def installZeo(self, ip, port, name, path):
    config = dict(
      zeo_ip=ip,
      zeo_port=port,
      zeo_storagename=name,
      zeo_event_log=os.path.join(self.log_directory, 'zeo.log'),
      zeo_pid=os.path.join(self.run_directory, 'zeo.pid'),
      zeo_zodb=path
    )
    zeo_conf_path = self.createConfigurationFile('zeo.conf',
      self.substituteTemplate(self.getTemplateFilename('zeo.conf.in'), config))
    self.path_list.append(zeo_conf_path)
    wrapper = zc.buildout.easy_install.scripts([('zeo', __name__ + '.execute',
      'execute')], self.ws, sys.executable, self.wrapper_directory, arguments=[
        self.options['runzeo_binary'].strip(), '-C', zeo_conf_path]
      )[0]
    self.path_list.append(wrapper)
    return dict(
      zeo_address='%s:%s' % (config['zeo_ip'], config['zeo_port']),
      zeo_storagename=config['zeo_storagename'])

  def installZope(self, ip, port, name, zeo_address=None, zeo_storagename=None,
      zodb_root_path=None, with_timerservice=False):
    # Create zope configuration file
    zope_config = dict(
        products=self.options['products'],
    )
    if zeo_address is not None and zeo_storagename is not None:
      zope_config.update(zeo_address=zeo_address, zeo_storagename=zeo_storagename)
    elif zodb_root_path is not None:
      zope_config.update(zodb_root_path=zodb_root_path)
    zope_config['instance'] = self.erp5_directory
    zope_config['event_log'] = os.path.join(self.log_directory,
        '%s-event.log' % name)
    zope_config['z2_log'] = os.path.join(self.log_directory,
        '%s-Z2.log' % name)
    zope_config['pid-filename'] = os.path.join(self.run_directory,
        '%s.pid' % name)
    zope_config['lock-filename'] = os.path.join(self.run_directory,
        '%s.lock' % name)

    prefixed_products = []
    for product in reversed(zope_config['products'].split()):
      product = product.strip()
      if product:
        prefixed_products.append('products %s' % product)
    prefixed_products.insert(0, 'products %s' % os.path.join(
                             self.erp5_directory, 'Products'))
    zope_config['products'] = '\n'.join(prefixed_products)
    zope_config['address'] = '%s:%s' % (ip, port)
    zope_config['tmp_directory'] = self.tmp_directory
    zope_config['path'] = ':'.join([self.bin_directory] +
        os.environ['PATH'].split(':'))

    if zeo_address is None:
      zope_wrapper_template_location = self.getTemplateFilename(
          'zope.conf.simple.in')
      with_timerservice = True
    else:
      zope_wrapper_template_location = self.getTemplateFilename('zope.conf.in')

    zope_conf_content = self.substituteTemplate(
        zope_wrapper_template_location, zope_config)
    if with_timerservice:
      zope_conf_content += self.substituteTemplate(
          self.getTemplateFilename('zope.conf.timerservice.in'), zope_config)
    zope_conf_path = self.createConfigurationFile("%s.conf" % name,
        zope_conf_content)
    self.path_list.append(zope_conf_path)
    # Create init script
    wrapper = zc.buildout.easy_install.scripts([(name,
      __name__ + '.execute', 'execute')], self.ws, sys.executable,
      self.wrapper_directory, arguments=[
        self.options['runzope_binary'].strip(), '-C', zope_conf_path]
      )[0]
    self.path_list.append(wrapper)
    return zope_config['address']

  def _getApacheConfigurationDict(self, prefix, ip, port):
    apache_conf = dict()
    apache_conf['pid_file'] = os.path.join(self.run_directory,
        prefix + '.pid')
    apache_conf['lock_file'] = os.path.join(self.run_directory,
        prefix + '.lock')
    apache_conf['ip'] = ip
    apache_conf['port'] = port
    apache_conf['server_admin'] = 'admin@'
    apache_conf['error_log'] = os.path.join(self.log_directory,
        prefix + '-error.log')
    apache_conf['access_log'] = os.path.join(self.log_directory,
        prefix + '-access.log')
    return apache_conf

  def _writeApacheConfiguration(self, prefix, apache_conf, backend):
    rewrite_rule_template = \
        "RewriteRule (.*) http://%(backend)s$1 [L,P]"
    path_template = pkg_resources.resource_string(__name__,
      'template/apache.zope.conf.path.in')
    path = path_template % dict(path='/')
    d = dict(
          path=path,
          backend=backend,
          backend_path='/',
          port=apache_conf['port'],
          vhname=path.replace('/', ''),
    )
    rewrite_rule = rewrite_rule_template % d
    apache_conf.update(**dict(
      path_enable=path,
      rewrite_rule=rewrite_rule
    ))
    return self.createConfigurationFile(prefix + '.conf',
        pkg_resources.resource_string(__name__,
          'template/apache.zope.conf.in') % apache_conf)

  def installLoginApache(self, ip, port, backend, key, certificate):
    ssl_template = """SSLEngine on
SSLCertificateFile %(login_certificate)s
SSLCertificateKeyFile %(login_key)s
SSLRandomSeed startup builtin
SSLRandomSeed connect builtin
"""
    apache_conf = self._getApacheConfigurationDict('login_apache', ip, port)
    apache_conf['server_name'] = '%s' % apache_conf['ip']
    apache_conf['ssl_snippet'] = ssl_template % dict(
        login_certificate=certificate, login_key=key)
    apache_config_file = self._writeApacheConfiguration('login_apache',
        apache_conf, backend)
    self.path_list.append(apache_config_file)
    self.path_list.extend(zc.buildout.easy_install.scripts([(
      'login_apache',
        __name__ + '.apache', 'runApache')], self.ws,
          sys.executable, self.wrapper_directory, arguments=[
            dict(
              required_path_list=[key, certificate],
              binary=self.options['httpd_binary'],
              config=apache_config_file
            )
          ]))
    # Note: IPv6 is assumed always
    return 'https://[%(ip)s]:%(port)s' % apache_conf

  def installMysqlServer(self, ip, port, database='erp5', user='user',
      test_database='test_erp5', test_user='test_user'):
    mysql_conf = dict(
        ip=ip,
        data_directory=os.path.join(self.data_root_directory,
          'mysql'),
        tcp_port=port,
        pid_file=os.path.join(self.run_directory, 'mysqld.pid'),
        socket=os.path.join(self.run_directory, 'mysqld.sock'),
        error_log=os.path.join(self.log_directory, 'mysqld.log'),
        slow_query_log=os.path.join(self.log_directory,
        'mysql-slow.log'),
        mysql_database=database,
        mysql_user=user,
        mysql_password=self.generatePassword(),
        mysql_test_password=self.generatePassword(),
        mysql_test_database=test_database,
        mysql_test_user=test_user,
        mysql_parallel_test_dict=[
            ('test_%i' % x,)*2 + (self.generatePassword(),) \
                 for x in xrange(0,100)],
    )
    self._createDirectory(mysql_conf['data_directory'])

    mysql_conf_path = self.createConfigurationFile("my.cnf",
        self.substituteTemplate(self.getTemplateFilename('my.cnf.in'),
          mysql_conf))

    mysql_script_list = []
    for x_database, x_user, x_password in \
          [(mysql_conf['mysql_database'],
            mysql_conf['mysql_user'],
            mysql_conf['mysql_password']),
           (mysql_conf['mysql_test_database'],
            mysql_conf['mysql_test_user'],
            mysql_conf['mysql_test_password']),
          ] + mysql_conf['mysql_parallel_test_dict']:
      mysql_script_list.append(pkg_resources.resource_string(__name__,
                     'template/initmysql.sql.in') % {
                        'mysql_database': x_database,
                        'mysql_user': x_user,
                        'mysql_password': x_password})
    mysql_script_list.append('EXIT')
    mysql_script = '\n'.join(mysql_script_list)
    self.path_list.extend(zc.buildout.easy_install.scripts([('mysql_update',
      __name__ + '.mysql', 'updateMysql')], self.ws,
      sys.executable, self.wrapper_directory, arguments=[dict(
        mysql_script=mysql_script,
        mysql_binary=self.options['mysql_binary'].strip(),
        mysql_upgrade_binary=self.options['mysql_upgrade_binary'].strip(),
        socket=mysql_conf['socket'],
        )]))
    self.path_list.extend(zc.buildout.easy_install.scripts([('mysqld',
      __name__ + '.mysql', 'runMysql')], self.ws,
        sys.executable, self.wrapper_directory, arguments=[dict(
        mysql_install_binary=self.options['mysql_install_binary'].strip(),
        mysqld_binary=self.options['mysqld_binary'].strip(),
        data_directory=mysql_conf['data_directory'].strip(),
        mysql_binary=self.options['mysql_binary'].strip(),
        socket=mysql_conf['socket'].strip(),
        configuration_file=mysql_conf_path,
       )]))
    self.path_list.extend([mysql_conf_path])
    # The return could be more explicit database, user ...
    return mysql_conf
