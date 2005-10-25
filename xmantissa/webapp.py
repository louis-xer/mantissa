"""
This module is the basis for Mantissa-based web applications.  It provides
several basic pluggable application-level features, most notably Powerup-based
integration of the extensible hierarchical navigation system defined in
xmantissa.webnav
"""

from zope.interface import implements

from axiom.item import Item
from axiom.attributes import text, integer, reference
from axiom.userbase import getAccountNames
from axiom import upgrade

from nevow.rend import Page, Fragment
from nevow import livepage, athena
from nevow.inevow import IResource, IQ
from nevow import tags as t
from nevow.url import URL

from xmantissa.publicweb import CustomizedPublicPage
from xmantissa.website import PrefixURLMixin, StaticRedirect
from xmantissa.webtheme import getAllThemes
from xmantissa.webnav import getTabs
from xmantissa._webidgen import genkey, storeIDToWebID, webIDToStoreID

from xmantissa.ixmantissa import INavigableFragment, INavigableElement,\
    ISiteRootPlugin, IWebTranslator, ISearchAggregator, IStaticShellContent

def _reorderForPreference(themeList, preferredThemeName):
    """
    Re-order the input themeList according to the preferred theme.

    Returns None.
    """
    for t in themeList:
        if preferredThemeName == t.themeName:
            themeList.remove(t)
            themeList.insert(0,t)
            return


class NavFragment(Fragment):
    def __init__(self, docFactory, navigation, webapp):
        Fragment.__init__(self, docFactory=docFactory)
        self.navigation = navigation
        self.webapp = webapp

    def render_tab(self, ctx, data):
        name = data.name
        subtabs = data.children
        self.subtabs = subtabs
        ctx.fillSlots('href', self.webapp.linkTo(data.storeID))
        ctx.fillSlots('name', name)
        if subtabs:
            st = NavFragment(self.docFactory, subtabs, self.webapp)
        else:
            st = ''
        ctx.fillSlots('subtabs', st)
        return ctx.tag

    def data_tabs(self, ctx, data):
        return self.navigation


class NavMixin(object):

    fragmentName = 'main'
    username = None
    searchPattern = None

    def __init__(self, webapp, navigation, searchable, staticContent):
        self.webapp = webapp
        self.navigation = navigation
        self.searchable = searchable
        self.staticContent = staticContent

    def getDocFactory(self, fragmentName, default=None):
        return self.webapp.getDocFactory(fragmentName, default)

    def render_content(self, ctx, data):
        raise NotImplementedError("implement render_context in subclasses")

    def render_navigation(self, ctx, data):
        return NavFragment(self.getDocFactory('navigation'),
                           self.navigation,
                           self.webapp)

    def render_title(self, ctx, data):
        return ctx.tag[self.__class__.__name__]

    def render_search(self, ctx, data):
        if self.searchable is None or not self.searchable.providers():
            return ctx.tag

        if self.searchPattern is None:
            self.searchPattern = IQ(self.docFactory).patternGenerator("search")

        action = self.webapp.linkTo(self.searchable.storeID)
        return ctx.tag[self.searchPattern.fillSlots('form-action', action)]

    def render_username(self, ctx, data):
        if self.username is None:
            for (user, domain) in getAccountNames(self.webapp.installedOn):
                self.username = '%s@%s' % (user, domain)
                break
            else:
                self.username = 'nobody@noplace'
        return ctx.tag[self.username]

    def render_head(self, ctx, data):
        return ctx.tag

    def render_header(self, ctx, data):
        if self.staticContent is None:
            return ctx.tag
        header = self.staticContent.getHeader()
        if header is not None:
            return ctx.tag[header]
        else:
            return ctx.tag

    def render_footer(self, ctx, data):
        if self.staticContent is None:
            return ctx.tag
        footer = self.staticContent.getFooter()
        if footer is not None:
            return ctx.tag[footer]
        else:
            return ctx.tag

class FragmentWrapperMixin:
    def __init__(self, fragment):
        self.fragment = fragment
        fragment.page = self

    def beforeRender(self, ctx):
        return getattr(self.fragment, 'beforeRender', lambda x: None)(ctx)

    def render_head(self, ctx, data):
        l = list(getAllThemes())
        _reorderForPreference(l, self.webapp.preferredTheme)
        extras = []
        for theme in l:
            extra = theme.head()
            if extra is not None:
                extras.append(extra)
        extra = self.fragment.head()
        if extra is not None:
            extras.append(extra)
        return ctx.tag[extras]

    def render_title(self, ctx, data):
        return ctx.tag[getattr(self.fragment, 'title', self.fragment.__class__.__name__)]

    def render_content(self, ctx, data):
        return ctx.tag[self.fragment]


class GenericNavigationPage(Page, FragmentWrapperMixin, NavMixin):
    def __init__(self, webapp, navigation, searchable, staticContent, fragment):
        Page.__init__(self, docFactory=webapp.getDocFactory('shell'))
        NavMixin.__init__(self, webapp, navigation, searchable, staticContent)
        FragmentWrapperMixin.__init__(self, fragment)


class GenericNavigationLivePage(livepage.LivePage, FragmentWrapperMixin, NavMixin):
    def __init__(self, webapp, navigation, searchable, staticContent, fragment):
        livepage.LivePage.__init__(self, docFactory=webapp.getDocFactory('shell'))
        NavMixin.__init__(self, webapp, navigation, searchable, staticContent)
        FragmentWrapperMixin.__init__(self, fragment)

    # XXX TODO: support live nav, live fragments somehow
    def render_head(self, ctx, data):
        ctx.tag[t.invisible(render=t.directive("liveglue"))]
        return FragmentWrapperMixin.render_head(self, ctx, data)

    def goingLive(self, ctx, client):
        getattr(self.fragment, 'goingLive', lambda x, y: None)(ctx, client)

    def locateHandler(self, ctx, path, name):
        return getattr(self.fragment, 'handle_' + name)


class GenericNavigationAthenaPage(athena.LivePage, FragmentWrapperMixin, NavMixin):
    def __init__(self):
        pass

    initialized = False

    def init(self, webapp, navigation, searchable, staticContent, fragment):
        if not self.initialized:
            self.initialized = True
            athena.LivePage.__init__(self, docFactory=webapp.getDocFactory('shell'))
            NavMixin.__init__(self, webapp, navigation, searchable, staticContent)
            FragmentWrapperMixin.__init__(self, fragment)

    def render_head(self, ctx, data):
        ctx.tag[t.invisible(render=t.directive("liveglue"))]
        return FragmentWrapperMixin.render_head(self, ctx, data)

    def locateMethod(self, ctx, methodName):
        return self.fragment.locateMethod(methodName)

_athenaFactory = athena.LivePageFactory(GenericNavigationAthenaPage)

class PrivateRootPage(Page, NavMixin):
    addSlash = True

    def __init__(self, webapp, navigation, searchable, staticContent):
        self.webapp = webapp
        Page.__init__(self, docFactory=webapp.getDocFactory('shell'))
        NavMixin.__init__(self, webapp, navigation, searchable, staticContent)
        self.searchable = searchable
        self.staticContent = staticContent

    def child_(self, ctx):
        if not self.navigation:
            return self
        # /private/XXXX ->
        click = self.webapp.linkTo(self.navigation[0].storeID)
        return URL.fromContext(ctx).click(click)

    def render_content(self, ctx, data):
        return """
        You have no default root page set, and no navigation plugins installed.  I
        don't know what to do.
        """

    def render_title(self, ctx, data):
        return ctx.tag['Private Root Page (You Should Not See This)']

    def childFactory(self, ctx, name):
        storeID = self.webapp.linkFrom(name)
        if storeID is None:
            return None

        o = self.webapp.store.getItemByID(storeID, None)
        if o is None:
            return None
        res = IResource(o, None)
        if res is not None:
            return res
        fragment = INavigableFragment(o, None)
        if fragment is None:
            return None
        if fragment.fragmentName is not None:
            fragDocFactory = self.webapp.getDocFactory(fragment.fragmentName, None)
            if fragDocFactory is not None:
                fragment.docFactory = fragDocFactory
        if fragment.docFactory is None:
            raise RuntimeError("%r (fragment name %r) has no docFactory" % (fragment, fragment.fragmentName))

        pageArgs = (self.webapp, self.navigation,
                    self.searchable, self.staticContent,
                    fragment)

        def athenaFactory(*args):
            page = _athenaFactory.clientFactory(ctx)
            page.init(*args)
            return page

        pageClass = {False: GenericNavigationPage,
         True: GenericNavigationLivePage,
         'athena': athenaFactory}.get(fragment.live)
        return pageClass(*pageArgs)


class PrivateApplication(Item, PrefixURLMixin):
    """
    This is the root of a private, navigable web application.  It is designed
    to be installed on avatar stores after installing WebSite.

    To plug into it, install powerups of the type INavigableElement on the
    user's store.  Their tabs will be retrieved and items that are part of
    those powerups will be linked to; provide adapters for said items to either
    INavigableFragment or IResource.

    Note: IResource adapters should be used sparingly, for example, for
    specialized web resources which are not 'nodes' within the application; for
    example, that need to set a custom content/type or that should not display
    any navigation elements because they will be displayed only within IFRAME
    nodes.  Do _NOT_ use IResource adapters to provide a customized
    look-and-feel; instead use mantissa themes.  (XXX document webtheme.py more
    thoroughly)

    @ivar preferredTheme: A C{unicode} string naming the preferred theme for
    this application.  Templates and suchlike will be looked up for this theme
    first.

    @ivar hitCount: Number of page loads of this application.

    @ivar privateKey: A random integer used to deterministically but
    unpredictably perturb link generation to avoid being the target of XSS
    attacks.

    @ivar privateIndexPage: A reference to the Item whose IResource or
    INavigableFragment adapter will be displayed on login and upon viewing the
    'root' page, /private/.
    """

    implements(ISiteRootPlugin, IWebTranslator)

    typeName = 'private_web_application'
    schemaVersion = 2

    installedOn = reference()

    preferredTheme = text()
    hitCount = integer()
    privateKey = integer()

    #XXX Nothing ever uses this
    privateIndexPage = reference()

    prefixURL = 'private'

    def __init__(self, **kw):
        super(PrivateApplication, self).__init__(**kw)
        gk = genkey()
        self.privateKey = gk

    def installOn(self, other):
        assert self.installedOn is None, "You cannot install a PrivateApplication on more than one Item"
        self.installedOn = other
        super(PrivateApplication, self).installOn(other)
        other.powerUp(self, IWebTranslator)
        other.store.findOrCreate(StaticRedirect,
                                 sessioned=True,
                                 sessionless=False,
                                 prefixURL=u'',
                                 targetURL=u'/'+self.prefixURL).installOn(other, -1)

        other.findOrCreate(
            CustomizedPublicPage,
            prefixURL=u'').installOn(other)


    def createResource(self):
        return PrivateRootPage(self,
                getTabs(self.installedOn.powerupsFor(INavigableElement)),
                ISearchAggregator(self.installedOn, None),
                IStaticShellContent(self.installedOn, None))

    # ISiteRootPlugin
    def resourceFactory(self, segments):
        return super(PrivateApplication, self).resourceFactory(segments)


    # IWebTranslator
    def linkTo(self, obj):
        # currently obj must be a storeID, but other types might come eventually
        return '/%s/%s' % (self.prefixURL, storeIDToWebID(self.privateKey, obj))

    def linkFrom(self, webid):
        return webIDToStoreID(self.privateKey, webid)

    def getDocFactory(self, fragmentName, default=None):
        l = list(getAllThemes())
        _reorderForPreference(l, self.preferredTheme)
        for t in l:
            fact = t.getDocFactory(fragmentName, None)
            if fact is not None:
                return fact
        return default

def upgradePrivateApplication1To2(oldApp):
    newApp = oldApp.upgradeVersion(
        'private_web_application', 1, 2,
        installedOn=oldApp.installedOn,
        preferredTheme=oldApp.preferredTheme,
        hitCount=oldApp.hitCount,
        privateKey=oldApp.privateKey,
        privateIndexPage=oldApp.privateIndexPage)
    newApp.installedOn.findOrCreate(
        CustomizedPublicPage,
        prefixURL=u'').installOn(newApp.installedOn)
    return newApp
upgrade.registerUpgrader(upgradePrivateApplication1To2, 'private_web_application', 1, 2)
