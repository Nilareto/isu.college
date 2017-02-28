from zope.interface import Interface
import zope.schema
from isu.onece.interfaces import ICatalogItem, ICatalogItemBase
from isu.onece.org.interfaces import IEmployee
from isu.onece.org.interfaces import IOrganization, ISpecification
from isu.onece.org.interfaces import IEmployee
from zope.i18nmessageid import MessageFactory
import isu.college.enums as enums

_ = MessageFactory("isu.college")


# FIXME: Add default values for the fields.

class ICollege(IOrganization):
    pass


class IFaculty(IOrganization):
    pass


class IProfessor(IEmployee):
    """The faculty stuff unit, e.g.,
    human teacher. ;-)
    """


class ICatalogItemSID(ICatalogItem):
    id = zope.schema.TextLine(
        title=_("Code"),
        description=_(
            "The code identifying the catalog "
            "item represented as a string."),
        required=True,
        readonly=False
    )


class IProfession(ICatalogItemSID):
    """Teaching profession
    """


class IDirection(IProfession):
    """The direction of Training.
    """


class IEducationalStandard(ICatalogItemBase):
    """Reference to a educational standard.
    """
    profession = zope.schema.Object(
        title=_("Teaching profession"),
        description=_("Reference to a teaching profession."),
        schema=IProfession,
        required=True
    )


class ICurriculum(ICatalogItemBase):
    """The curriculum supposed to be referenced from
    an IOrganization subdivision.
    """
    standard = zope.schema.Object(
        title=_("Educational standard"),
        description=_("Reference to an educational standard."),
        schema=IEducationalStandard,
        required=True
    )


class IEducationalSpecification(ISpecification):
    """A specification variation referring to
    a ICurriculum provider.
    """

    curriculum = zope.schema.Object(
        title=_("Curriculum"),
        description=_("The Curriculum the working program belongs to."),
        schema=ICurriculum,
        required=True
    )

    author = zope.schema.Object(
        title=_("Author"),
        description=_("The author of the specification"),
        schema=IProfessor,
    )


class IWorkingProgram(IEducationalSpecification):
    """The working program of discipline
    """
