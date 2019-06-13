# -*- coding: utf-8 -*-

import uuid

from gluon import *
from s3 import S3CustomController, s3_mark_required

THEME = "VM/CCC"

# =============================================================================
class index(S3CustomController):
    """ Custom Home Page """

    def __call__(self):

        output = {}

        # Allow editing of page content from browser using CMS module
        if current.deployment_settings.has_module("cms"):
            system_roles = current.auth.get_system_roles()
            ADMIN = system_roles.ADMIN in current.session.s3.roles
            s3db = current.s3db
            table = s3db.cms_post
            ltable = s3db.cms_post_module
            module = "default"
            resource = "index"
            query = (ltable.module == module) & \
                    ((ltable.resource == None) | \
                     (ltable.resource == resource)) & \
                    (ltable.post_id == table.id) & \
                    (table.deleted != True)
            item = current.db(query).select(table.body,
                                            table.id,
                                            limitby=(0, 1)).first()
            if item:
                if ADMIN:
                    item = DIV(XML(item.body),
                               BR(),
                               A(current.T("Edit"),
                                 _href = URL(c="cms", f="post",
                                             args = [item.id, "update"],
                                             vars = {"module": module,
                                                     "resource": resource,
                                                     },
                                             ),
                                 _class="action-btn",
                                 ),
                               )
                else:
                    item = DIV(XML(item.body))
            elif ADMIN:
                if current.response.s3.crud.formstyle == "bootstrap":
                    _class = "btn"
                else:
                    _class = "action-btn"
                item = A(current.T("Edit"),
                         _href = URL(c="cms", f="post", args="create",
                                     vars = {"module": module,
                                             "resource": resource,
                                             },
                                     ),
                         _class="%s cms-edit" % _class,
                         )
            else:
                item = ""
        else:
            item = ""
        output["item"] = item

        self._view(THEME, "index.html")
        return output

# =============================================================================
class register(S3CustomController):
    """ Custom Registration Page """

    def __call__(self):

        T = current.T
        db = current.db
        s3db = current.s3db

        request = current.request
        response = current.response
        session = current.session
        settings = current.deployment_settings

        auth = current.auth
        auth_settings = auth.settings
        auth_messages = auth.messages

        # Redirect if already logged-in
        if auth.is_logged_in():
            redirect(auth_settings.logged_url)

        utable = auth_settings.table_user
        passfield = auth_settings.password_field

        # Instantiate Consent Tracker
        # TODO: limit to relevant data processing types
        consent = s3db.auth_Consent()

        # Form Fields
        required_fields = []
        formfields = [utable.first_name,
                      utable.last_name,
                      utable.email,
                      utable[passfield],
                      # Password Verification Field
                      Field("password_two", "password",
                            label = auth_messages.verify_password,
                            requires = IS_EXPR("value==%s" % \
                                               repr(request.vars.get(passfield)),
                                               error_message = auth_messages.mismatched_password,
                                               ),
                            ),
                      # Consent Question
                      Field("consent_question",
                            label = T("Consent"),
                            widget = consent.widget,
                            ),
                      ]

        # Mobile Phone (optional)
        if settings.get_auth_registration_requests_mobile_phone():
            label = settings.get_ui_label_mobile_phone()
            formfields.insert(-1, Field("mobile",
                                        label = label,
                                        comment = DIV(_class = "tooltip",
                                                      _title = "%s|%s" % (label, auth_messages.help_mobile_phone),
                                                      ),

                                        ))
            if settings.get_auth_registration_mobile_phone_mandatory():
                required_fields.append("mobile")

        # Generate labels (and mark required fields in the process)
        labels = s3_mark_required(formfields, mark_required=required_fields)[0]

        # Form buttons
        REGISTER = T("Register")
        buttons = [INPUT(_type="submit", _value=REGISTER),
                   A(T("Login"),
                     _href=URL(f="user", args="login"),
                     _id="login-btn",
                     _class="action-lnk",
                     ),
                   ]

        # Construct the form
        response.form_label_separator = ""
        form = SQLFORM.factory(table_name = utable._tablename,
                               record = None,
                               hidden = {"_next": request.vars._next},
                               labels = labels,
                               separator = "",
                               showid = False,
                               submit_button = REGISTER,
                               delete_label = auth_messages.delete_label,
                               formstyle = settings.get_ui_formstyle(),
                               buttons = buttons,
                               *formfields)

        # Identify form for CSS & JS Validation
        form.add_class("auth_register")

        # Inject client-side Validation
        auth.s3_register_validation()

        # Captcha, if configured
        if auth_settings.captcha != None:
            form[0].insert(-1, DIV("", auth_settings.captcha, ""))

        # Set default registration key, so new users are prevented
        # from logging in until approved
        utable.registration_key.default = key = str(uuid.uuid4())

        if form.accepts(request.vars,
                        session,
                        formname = "register",
                        onvalidation = auth_settings.register_onvalidation,
                        ):

            # Create the user record
            user_id = utable.insert(**utable._filter_fields(form.vars, id=False))
            form.vars.id = user_id

            # Save temporary user fields
            auth.s3_user_register_onaccept(form)

            # Where to go next?
            register_next = request.vars._next or auth_settings.register_next

            # Post-process the new user record
            users = db(utable.id > 0).select(utable.id, limitby=(0, 2))
            if len(users) == 1:
                # 1st user to register doesn't need verification/approval
                auth.s3_approve_user(form.vars)
                current.session.confirmation = auth_messages.registration_successful

                # 1st user gets Admin rights
                admin_group_id = 1
                auth.add_membership(admin_group_id, users.first().id)

                # Log them in
                if "language" not in form.vars:
                    # Was missing from login form
                    form.vars.language = T.accepted_language
                user = Storage(utable._filter_fields(form.vars, id=True))
                auth.login_user(user)

                # Send welcome email
                auth.s3_send_welcome_email(form.vars)

            elif auth_settings.registration_requires_verification:
                # System Details for Verification Email
                system = {"system_name": settings.get_system_name(),
                          "url": "%s/default/user/verify_email/%s" % (response.s3.base_url, key),
                          }

                # Try to send the Verification Email
                if not auth_settings.mailer or \
                   not auth_settings.mailer.settings.server or \
                   not auth_settings.mailer.send(to = form.vars.email,
                                                 subject = auth_messages.verify_email_subject % system,
                                                 message = auth_messages.verify_email % system,
                                                 ):
                    response.error = auth_messages.email_verification_failed
                    return form

                # Redirect to Verification Info page
                register_next = URL(c = "default",
                                    f = "message",
                                    args = ["verify_email_sent"],
                                    vars = {"email": form.vars.email},
                                    )

            else:
                # Does the user need to be approved?
                approved = auth.s3_verify_user(form.vars)

                if approved:
                    # Log them in
                    if "language" not in form.vars:
                        # Was missing from login form
                        form.vars.language = T.accepted_language
                    user = Storage(utable._filter_fields(form.vars, id=True))
                    auth.login_user(user)

            # Set a Cookie to present user with login box by default
            auth.set_cookie()

            # Log action
            log = auth_messages.register_log
            if log:
                auth.log_event(log, form.vars)

            # Run onaccept for registration form
            onaccept = auth_settings.register_onaccept
            if onaccept:
                onaccept(form)

            # Redirect
            if not register_next:
                register_next = auth.url(args = request.args)
            elif isinstance(register_next, (list, tuple)):
                # fix issue with 2.6
                register_next = register_next[0]
            elif register_next and not register_next[0] == "/" and register_next[:4] != "http":
                register_next = auth.url(register_next.replace("[id]", str(form.vars.id)))
            redirect(register_next)

        # Custom View
        self._view(THEME, "register.html")

        return {"title": T("Register"),
                "form": form,
                }

# END =========================================================================
