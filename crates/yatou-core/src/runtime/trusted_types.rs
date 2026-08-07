//! Native Chrome-150-compatible Trusted Types surface.

// rusty_v8 callback ABI takes FunctionCallbackArguments by value.
#![allow(clippy::needless_pass_by_value)]

use std::convert::TryFrom;

use super::{JsValueKind, V8Error, record_native, summary};

const VALUE: &str = "yatouv8.trusted_types.value";
const BRAND_HTML: &str = "yatouv8.trusted_types.brand.html";
const BRAND_SCRIPT: &str = "yatouv8.trusted_types.brand.script";
const BRAND_SCRIPT_URL: &str = "yatouv8.trusted_types.brand.script_url";
const POLICY_NAME: &str = "yatouv8.trusted_types.policy.name";
const POLICY_FACTORY: &str = "yatouv8.trusted_types.policy.factory";
const RULE_HTML: &str = "yatouv8.trusted_types.policy.rule.html";
const RULE_SCRIPT: &str = "yatouv8.trusted_types.policy.rule.script";
const RULE_SCRIPT_URL: &str = "yatouv8.trusted_types.policy.rule.script_url";
const PROTOTYPE_POLICY: &str = "yatouv8.trusted_types.prototype.policy";
const PROTOTYPE_HTML: &str = "yatouv8.trusted_types.prototype.html";
const PROTOTYPE_SCRIPT: &str = "yatouv8.trusted_types.prototype.script";
const PROTOTYPE_SCRIPT_URL: &str = "yatouv8.trusted_types.prototype.script_url";
const EMPTY_HTML: &str = "yatouv8.trusted_types.empty.html";
const EMPTY_SCRIPT: &str = "yatouv8.trusted_types.empty.script";
const DEFAULT_POLICY: &str = "yatouv8.trusted_types.default_policy";

#[derive(Clone, Copy)]
enum TrustedKind {
    Html,
    Script,
    ScriptUrl,
}

impl TrustedKind {
    const fn brand(self) -> &'static str {
        match self {
            Self::Html => BRAND_HTML,
            Self::Script => BRAND_SCRIPT,
            Self::ScriptUrl => BRAND_SCRIPT_URL,
        }
    }

    const fn prototype(self) -> &'static str {
        match self {
            Self::Html => PROTOTYPE_HTML,
            Self::Script => PROTOTYPE_SCRIPT,
            Self::ScriptUrl => PROTOTYPE_SCRIPT_URL,
        }
    }

    const fn interface(self) -> &'static str {
        match self {
            Self::Html => "TrustedHTML",
            Self::Script => "TrustedScript",
            Self::ScriptUrl => "TrustedScriptURL",
        }
    }
}

fn string<'s>(scope: &mut v8::PinScope<'s, '_>, value: &str) -> Option<v8::Local<'s, v8::String>> {
    v8::String::new(scope, value)
}

fn private<'s>(scope: &mut v8::PinScope<'s, '_>, name: &str) -> Option<v8::Local<'s, v8::Private>> {
    let name = string(scope, name)?;
    Some(v8::Private::for_api(scope, Some(name)))
}

fn hidden_set(
    scope: &mut v8::PinScope,
    object: v8::Local<v8::Object>,
    name: &str,
    value: v8::Local<v8::Value>,
) -> bool {
    let Some(key) = private(scope, name) else {
        return false;
    };
    object.set_private(scope, key, value).unwrap_or(false)
}

fn hidden_get<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    object: v8::Local<v8::Object>,
    name: &str,
) -> Option<v8::Local<'s, v8::Value>> {
    let key = private(scope, name)?;
    object.get_private(scope, key)
}

fn hidden_has(scope: &mut v8::PinScope, object: v8::Local<v8::Object>, name: &str) -> bool {
    let Some(key) = private(scope, name) else {
        return false;
    };
    object.has_private(scope, key).unwrap_or(false)
}

fn object_hidden<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    object: v8::Local<v8::Object>,
    name: &str,
) -> Option<v8::Local<'s, v8::Object>> {
    v8::Local::<v8::Object>::try_from(hidden_get(scope, object, name)?).ok()
}

fn throw_type_error(scope: &mut v8::PinScope, message: &str) {
    if let Some(message) = v8::String::new(scope, message) {
        let exception = v8::Exception::type_error(scope, message);
        scope.throw_exception(exception);
    }
}

fn define_data(
    scope: &mut v8::PinScope,
    object: v8::Local<v8::Object>,
    name: &'static str,
    value: v8::Local<v8::Value>,
    attributes: v8::PropertyAttribute,
) -> Result<(), V8Error> {
    let key = string(scope, name).ok_or(V8Error::SourceAllocation)?;
    if object
        .define_own_property(scope, key.into(), value, attributes)
        .unwrap_or(false)
    {
        Ok(())
    } else {
        Err(V8Error::NativeInstallation(name))
    }
}

fn define_getter(
    scope: &mut v8::PinScope,
    object: v8::Local<v8::Object>,
    name: &'static str,
    getter: v8::Local<v8::Function>,
) -> Result<(), V8Error> {
    let key = string(scope, name).ok_or(V8Error::SourceAllocation)?;
    let mut descriptor =
        v8::PropertyDescriptor::new_from_get_set(getter.into(), v8::undefined(scope).into());
    descriptor.set_enumerable(true);
    descriptor.set_configurable(true);
    if object
        .define_property(scope, key.into(), &descriptor)
        .unwrap_or(false)
    {
        Ok(())
    } else {
        Err(V8Error::NativeInstallation(name))
    }
}

fn named_function<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    name: &'static str,
    length: i32,
    callback: impl v8::MapFnTo<v8::FunctionCallback>,
) -> Result<v8::Local<'s, v8::Function>, V8Error> {
    let function = v8::Function::builder(callback)
        .length(length)
        .build(scope)
        .ok_or(V8Error::NativeInstallation(name))?;
    let function_name = string(scope, name).ok_or(V8Error::SourceAllocation)?;
    function.set_name(function_name);
    Ok(function)
}

fn named_getter<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    property: &'static str,
    callback: impl v8::MapFnTo<v8::FunctionCallback>,
) -> Result<v8::Local<'s, v8::Function>, V8Error> {
    let function = v8::Function::builder(callback)
        .length(0)
        .build(scope)
        .ok_or(V8Error::NativeInstallation(property))?;
    let name = format!("get {property}");
    let name = string(scope, &name).ok_or(V8Error::SourceAllocation)?;
    function.set_name(name);
    Ok(function)
}

fn illegal_constructor(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    _retval: v8::ReturnValue,
) {
    let name = args.data().to_rust_string_lossy(scope);
    throw_type_error(
        scope,
        &format!("Failed to construct '{name}': Illegal constructor"),
    );
}

fn interface_constructor<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    name: &'static str,
) -> Result<(v8::Local<'s, v8::Function>, v8::Local<'s, v8::Object>), V8Error> {
    let data = string(scope, name).ok_or(V8Error::SourceAllocation)?;
    let constructor = v8::Function::builder(illegal_constructor)
        .data(data.into())
        .length(0)
        .build(scope)
        .ok_or(V8Error::NativeInstallation(name))?;
    constructor.set_name(data);
    let prototype_key = string(scope, "prototype").ok_or(V8Error::SourceAllocation)?;
    let prototype = constructor
        .get(scope, prototype_key.into())
        .and_then(|value| v8::Local::<v8::Object>::try_from(value).ok())
        .ok_or(V8Error::NativeInstallation(name))?;
    let constructor_key = string(scope, "constructor").ok_or(V8Error::SourceAllocation)?;
    let _ = prototype.delete(scope, constructor_key.into());
    let tag = v8::Symbol::get_to_string_tag(scope);
    if !prototype
        .define_own_property(
            scope,
            tag.into(),
            data.into(),
            v8::PropertyAttribute::READ_ONLY | v8::PropertyAttribute::DONT_ENUM,
        )
        .unwrap_or(false)
    {
        return Err(V8Error::NativeInstallation(name));
    }
    Ok((constructor, prototype))
}

fn finish_prototype(
    scope: &mut v8::PinScope,
    prototype: v8::Local<v8::Object>,
    constructor: v8::Local<v8::Function>,
) -> Result<(), V8Error> {
    define_data(
        scope,
        prototype,
        "constructor",
        constructor.into(),
        v8::PropertyAttribute::DONT_ENUM,
    )
}

fn trusted_value<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    factory: v8::Local<v8::Object>,
    kind: TrustedKind,
    value: v8::Local<v8::String>,
) -> Option<v8::Local<'s, v8::Object>> {
    let prototype = object_hidden(scope, factory, kind.prototype())?;
    let object = v8::Object::new(scope);
    if !object
        .set_prototype(scope, prototype.into())
        .unwrap_or(false)
        || !hidden_set(scope, object, VALUE, value.into())
        || !hidden_set(
            scope,
            object,
            kind.brand(),
            v8::Boolean::new(scope, true).into(),
        )
    {
        return None;
    }
    Some(object)
}

fn trusted_string(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
    kind: TrustedKind,
) {
    let receiver = args.this();
    if !hidden_has(scope, receiver, kind.brand()) {
        throw_type_error(scope, "Illegal invocation");
        return;
    }
    let Some(value) = hidden_get(scope, receiver, VALUE) else {
        throw_type_error(scope, "Illegal invocation");
        return;
    };
    retval.set(value);
}

fn trusted_html_string(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    trusted_string(scope, args, retval, TrustedKind::Html);
}

fn trusted_script_string(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    trusted_string(scope, args, retval, TrustedKind::Script);
}

fn trusted_script_url_string(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    trusted_string(scope, args, retval, TrustedKind::ScriptUrl);
}

fn policy_name_getter(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let receiver = args.this();
    let Some(name) = hidden_get(scope, receiver, POLICY_NAME) else {
        throw_type_error(scope, "Illegal invocation");
        return;
    };
    if name.is_undefined() {
        throw_type_error(scope, "Illegal invocation");
        return;
    }
    retval.set(name);
}

fn policy_create(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
    kind: TrustedKind,
    rule_key: &'static str,
    method: &'static str,
) {
    let policy = args.this();
    let Some(name_value) = hidden_get(scope, policy, POLICY_NAME) else {
        throw_type_error(scope, "Illegal invocation");
        return;
    };
    if name_value.is_undefined() {
        throw_type_error(scope, "Illegal invocation");
        return;
    }
    let policy_name = name_value.to_rust_string_lossy(scope);
    let Some(rule_value) = hidden_get(scope, policy, rule_key) else {
        throw_type_error(scope, "Illegal invocation");
        return;
    };
    if rule_value.is_undefined() {
        throw_type_error(
            scope,
            &format!(
                "Failed to execute '{method}' on 'TrustedTypePolicy': Policy {policy_name}'s TrustedTypePolicyOptions did not specify a '{method}' member."
            ),
        );
        return;
    }
    let Ok(rule) = v8::Local::<v8::Function>::try_from(rule_value) else {
        throw_type_error(scope, "Illegal invocation");
        return;
    };
    let Some(input) = args.get(0).to_string(scope) else {
        return;
    };
    let mut arguments = Vec::with_capacity(usize::try_from(args.length().max(1)).unwrap_or(1));
    arguments.push(input.into());
    for index in 1..args.length() {
        arguments.push(args.get(index));
    }
    let receiver = v8::undefined(scope).into();
    let Some(result) = rule.call(scope, receiver, &arguments) else {
        return;
    };
    let Some(result) = result.to_string(scope) else {
        return;
    };
    let Some(factory) = object_hidden(scope, policy, POLICY_FACTORY) else {
        throw_type_error(scope, "Illegal invocation");
        return;
    };
    let Some(value) = trusted_value(scope, factory, kind, result) else {
        throw_type_error(scope, "Trusted Types value allocation failed");
        return;
    };
    record_native(
        "TrustedTypePolicy.prototype",
        method,
        vec![summary(JsValueKind::String, "string")],
        summary(JsValueKind::Object, kind.interface()),
    );
    retval.set(value.into());
}

fn policy_create_html(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    policy_create(
        scope,
        args,
        retval,
        TrustedKind::Html,
        RULE_HTML,
        "createHTML",
    );
}

fn policy_create_script(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    policy_create(
        scope,
        args,
        retval,
        TrustedKind::Script,
        RULE_SCRIPT,
        "createScript",
    );
}

fn policy_create_script_url(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    policy_create(
        scope,
        args,
        retval,
        TrustedKind::ScriptUrl,
        RULE_SCRIPT_URL,
        "createScriptURL",
    );
}

fn option_rule<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    options: v8::Local<v8::Object>,
    property: &'static str,
) -> Result<Option<v8::Local<'s, v8::Function>>, ()> {
    let Some(key) = string(scope, property) else {
        return Err(());
    };
    let Some(value) = options.get(scope, key.into()) else {
        return Err(());
    };
    if value.is_undefined() {
        return Ok(None);
    }
    if let Ok(function) = v8::Local::<v8::Function>::try_from(value) {
        Ok(Some(function))
    } else {
        throw_type_error(
            scope,
            &format!(
                "Failed to execute 'createPolicy' on 'TrustedTypePolicyFactory': Failed to read the '{property}' property from 'TrustedTypePolicyOptions': The given value is not a function."
            ),
        );
        Err(())
    }
}

fn factory_create_policy(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    if args.length() < 1 {
        throw_type_error(
            scope,
            "Failed to execute 'createPolicy' on 'TrustedTypePolicyFactory': 1 argument required, but only 0 present.",
        );
        return;
    }
    let factory = args.this();
    if !hidden_has(scope, factory, PROTOTYPE_POLICY) {
        throw_type_error(scope, "Illegal invocation");
        return;
    }
    let Some(name) = args.get(0).to_string(scope) else {
        return;
    };
    let policy_name = name.to_rust_string_lossy(scope);
    if policy_name == "default" && hidden_has(scope, factory, DEFAULT_POLICY) {
        throw_type_error(scope, "Policy with name \"default\" already exists.");
        return;
    }
    let options = if args.length() < 2 || args.get(1).is_null_or_undefined() {
        v8::Object::new(scope)
    } else {
        let Some(options) = args.get(1).to_object(scope) else {
            return;
        };
        options
    };
    let Ok(html_rule) = option_rule(scope, options, "createHTML") else {
        return;
    };
    let Ok(script_rule) = option_rule(scope, options, "createScript") else {
        return;
    };
    let Ok(script_url_rule) = option_rule(scope, options, "createScriptURL") else {
        return;
    };
    let Some(prototype) = object_hidden(scope, factory, PROTOTYPE_POLICY) else {
        throw_type_error(scope, "TrustedTypePolicy allocation failed");
        return;
    };
    let policy = v8::Object::new(scope);
    if !policy
        .set_prototype(scope, prototype.into())
        .unwrap_or(false)
        || !hidden_set(scope, policy, POLICY_NAME, name.into())
        || !hidden_set(scope, policy, POLICY_FACTORY, factory.into())
    {
        throw_type_error(scope, "TrustedTypePolicy allocation failed");
        return;
    }
    for (key, rule) in [
        (RULE_HTML, html_rule),
        (RULE_SCRIPT, script_rule),
        (RULE_SCRIPT_URL, script_url_rule),
    ] {
        if let Some(rule) = rule
            && !hidden_set(scope, policy, key, rule.into())
        {
            throw_type_error(scope, "TrustedTypePolicy allocation failed");
            return;
        }
    }
    if policy_name == "default" && !hidden_set(scope, factory, DEFAULT_POLICY, policy.into()) {
        throw_type_error(scope, "TrustedTypePolicy allocation failed");
        return;
    }
    record_native(
        "TrustedTypePolicyFactory.prototype",
        "createPolicy",
        vec![summary(JsValueKind::String, policy_name)],
        summary(JsValueKind::Object, "TrustedTypePolicy"),
    );
    retval.set(policy.into());
}

fn factory_empty_html(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let Some(value) = hidden_get(scope, args.this(), EMPTY_HTML) else {
        throw_type_error(scope, "Illegal invocation");
        return;
    };
    retval.set(value);
}

fn factory_empty_script(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let Some(value) = hidden_get(scope, args.this(), EMPTY_SCRIPT) else {
        throw_type_error(scope, "Illegal invocation");
        return;
    };
    retval.set(value);
}

fn factory_default_policy(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let factory = args.this();
    if !hidden_has(scope, factory, PROTOTYPE_POLICY) {
        throw_type_error(scope, "Illegal invocation");
        return;
    }
    if hidden_has(scope, factory, DEFAULT_POLICY) {
        if let Some(value) = hidden_get(scope, factory, DEFAULT_POLICY) {
            retval.set(value);
        }
    } else {
        retval.set_null();
    }
}

fn factory_is(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
    kind: TrustedKind,
    member: &'static str,
) {
    let factory = args.this();
    if !hidden_has(scope, factory, PROTOTYPE_POLICY) {
        throw_type_error(scope, "Illegal invocation");
        return;
    }
    let value = args.get(0);
    let result = value.is_object()
        && v8::Local::<v8::Object>::try_from(value)
            .ok()
            .is_some_and(|value| hidden_has(scope, value, kind.brand()));
    record_native(
        "TrustedTypePolicyFactory.prototype",
        member,
        vec![summary(JsValueKind::Object, "value")],
        summary(JsValueKind::Boolean, result.to_string()),
    );
    retval.set(v8::Boolean::new(scope, result).into());
}

fn factory_is_html(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    factory_is(scope, args, retval, TrustedKind::Html, "isHTML");
}

fn factory_is_script(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    factory_is(scope, args, retval, TrustedKind::Script, "isScript");
}

fn factory_is_script_url(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    factory_is(scope, args, retval, TrustedKind::ScriptUrl, "isScriptURL");
}

fn argument_string(
    scope: &mut v8::PinScope,
    args: &v8::FunctionCallbackArguments,
    index: i32,
) -> Option<String> {
    args.get(index)
        .to_string(scope)
        .map(|value| value.to_rust_string_lossy(scope))
}

fn sink_type(tag: &str, member: &str, attribute: bool) -> Option<&'static str> {
    let tag = tag.to_ascii_lowercase();
    if attribute {
        let member = member.to_ascii_lowercase();
        match (tag.as_str(), member.as_str()) {
            ("embed" | "script", "src") | ("object", "codebase" | "data") => {
                Some("TrustedScriptURL")
            }
            ("iframe", "srcdoc") => Some("TrustedHTML"),
            (_, event) if event.starts_with("on") => Some("TrustedScript"),
            _ => None,
        }
    } else {
        match (tag.as_str(), member) {
            ("embed" | "script", "src") | ("object", "codeBase" | "data") => {
                Some("TrustedScriptURL")
            }
            ("iframe", "srcdoc") | (_, "innerHTML" | "outerHTML") => Some("TrustedHTML"),
            ("script", "innerText" | "text" | "textContent") => Some("TrustedScript"),
            _ => None,
        }
    }
}

fn factory_type_query(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
    attribute: bool,
) {
    if args.length() < 2 {
        let method = if attribute {
            "getAttributeType"
        } else {
            "getPropertyType"
        };
        throw_type_error(
            scope,
            &format!(
                "Failed to execute '{method}' on 'TrustedTypePolicyFactory': 2 arguments required."
            ),
        );
        return;
    }
    if !hidden_has(scope, args.this(), PROTOTYPE_POLICY) {
        throw_type_error(scope, "Illegal invocation");
        return;
    }
    let Some(tag) = argument_string(scope, &args, 0) else {
        return;
    };
    let Some(member) = argument_string(scope, &args, 1) else {
        return;
    };
    if args.length() > 2 {
        let Some(namespace) = argument_string(scope, &args, 2) else {
            return;
        };
        if !namespace.is_empty() {
            retval.set_null();
            return;
        }
    }
    if attribute && args.length() > 3 {
        let Some(namespace) = argument_string(scope, &args, 3) else {
            return;
        };
        if !namespace.is_empty() {
            retval.set_null();
            return;
        }
    }
    if let Some(kind) = sink_type(&tag, &member, attribute) {
        if let Some(value) = string(scope, kind) {
            retval.set(value.into());
        }
    } else {
        retval.set_null();
    }
}

fn factory_get_attribute_type(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    factory_type_query(scope, args, retval, true);
}

fn factory_get_property_type(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    retval: v8::ReturnValue,
) {
    factory_type_query(scope, args, retval, false);
}

fn set_object_string(
    scope: &mut v8::PinScope,
    object: v8::Local<v8::Object>,
    name: &str,
    value: &str,
) -> bool {
    let Some(name) = string(scope, name) else {
        return false;
    };
    let Some(value) = string(scope, value) else {
        return false;
    };
    object
        .set(scope, name.into(), value.into())
        .unwrap_or(false)
}

fn mapping_entry(
    scope: &mut v8::PinScope,
    top: v8::Local<v8::Object>,
    tag: &str,
    properties: &[(&str, &str)],
    attributes: &[(&str, &str)],
) -> bool {
    let middle = v8::Object::new(scope);
    let property_map = v8::Object::new(scope);
    let attribute_map = v8::Object::new(scope);
    for (name, value) in properties {
        if !set_object_string(scope, property_map, name, value) {
            return false;
        }
    }
    for (name, value) in attributes {
        if !set_object_string(scope, attribute_map, name, value) {
            return false;
        }
    }
    let Some(properties_key) = string(scope, "properties") else {
        return false;
    };
    let Some(attributes_key) = string(scope, "attributes") else {
        return false;
    };
    let Some(tag_key) = string(scope, tag) else {
        return false;
    };
    middle
        .set(scope, properties_key.into(), property_map.into())
        .unwrap_or(false)
        && middle
            .set(scope, attributes_key.into(), attribute_map.into())
            .unwrap_or(false)
        && top
            .set(scope, tag_key.into(), middle.into())
            .unwrap_or(false)
}

fn factory_get_type_mapping(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    if !hidden_has(scope, args.this(), PROTOTYPE_POLICY) {
        throw_type_error(scope, "Illegal invocation");
        return;
    }
    if args.length() > 0 && !args.get(0).is_undefined() {
        let Some(namespace) = argument_string(scope, &args, 0) else {
            return;
        };
        if !namespace.is_empty() {
            retval.set_null();
            return;
        }
    }
    let top = v8::Object::new(scope);
    let entries = [
        (
            "embed",
            &[("src", "TrustedScriptURL")][..],
            &[("src", "TrustedScriptURL")][..],
        ),
        (
            "iframe",
            &[("srcdoc", "TrustedHTML")][..],
            &[("srcdoc", "TrustedHTML")][..],
        ),
        (
            "object",
            &[
                ("codeBase", "TrustedScriptURL"),
                ("data", "TrustedScriptURL"),
            ][..],
            &[
                ("codeBase", "TrustedScriptURL"),
                ("data", "TrustedScriptURL"),
            ][..],
        ),
        (
            "script",
            &[
                ("innerText", "TrustedScript"),
                ("src", "TrustedScriptURL"),
                ("text", "TrustedScript"),
                ("textContent", "TrustedScript"),
            ][..],
            &[("src", "TrustedScriptURL")][..],
        ),
        (
            "*",
            &[("innerHTML", "TrustedHTML"), ("outerHTML", "TrustedHTML")][..],
            &[][..],
        ),
    ];
    if entries
        .iter()
        .all(|(tag, properties, attributes)| mapping_entry(scope, top, tag, properties, attributes))
    {
        retval.set(top.into());
    } else {
        throw_type_error(scope, "Trusted Types mapping allocation failed");
    }
}

fn global_trusted_types(
    _scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    retval.set(args.data());
}

fn install_value_interface<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    global: v8::Local<'s, v8::Object>,
    name: &'static str,
    kind: TrustedKind,
    callback: impl v8::MapFnTo<v8::FunctionCallback> + Copy,
) -> Result<(v8::Local<'s, v8::Function>, v8::Local<'s, v8::Object>), V8Error> {
    let (constructor, prototype) = interface_constructor(scope, name)?;
    let to_json = named_function(scope, "toJSON", 0, callback)?;
    define_data(
        scope,
        prototype,
        "toJSON",
        to_json.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let to_string = named_function(scope, "toString", 0, callback)?;
    define_data(
        scope,
        prototype,
        "toString",
        to_string.into(),
        v8::PropertyAttribute::NONE,
    )?;
    finish_prototype(scope, prototype, constructor)?;
    define_data(
        scope,
        global,
        name,
        constructor.into(),
        v8::PropertyAttribute::DONT_ENUM,
    )?;
    debug_assert_eq!(kind.interface(), name);
    Ok((constructor, prototype))
}

#[allow(clippy::too_many_lines)]
pub(super) fn install(
    scope: &mut v8::PinScope,
    context: v8::Local<v8::Context>,
) -> Result<(), V8Error> {
    let global = context.global(scope);
    let (_, html_prototype) = install_value_interface(
        scope,
        global,
        "TrustedHTML",
        TrustedKind::Html,
        trusted_html_string,
    )?;
    let (_, script_prototype) = install_value_interface(
        scope,
        global,
        "TrustedScript",
        TrustedKind::Script,
        trusted_script_string,
    )?;
    let (_, script_url_prototype) = install_value_interface(
        scope,
        global,
        "TrustedScriptURL",
        TrustedKind::ScriptUrl,
        trusted_script_url_string,
    )?;

    let (policy_constructor, policy_prototype) = interface_constructor(scope, "TrustedTypePolicy")?;
    let name_getter = named_getter(scope, "name", policy_name_getter)?;
    define_getter(scope, policy_prototype, "name", name_getter)?;
    let create_html = named_function(scope, "createHTML", 1, policy_create_html)?;
    define_data(
        scope,
        policy_prototype,
        "createHTML",
        create_html.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let create_script = named_function(scope, "createScript", 1, policy_create_script)?;
    define_data(
        scope,
        policy_prototype,
        "createScript",
        create_script.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let create_script_url = named_function(scope, "createScriptURL", 1, policy_create_script_url)?;
    define_data(
        scope,
        policy_prototype,
        "createScriptURL",
        create_script_url.into(),
        v8::PropertyAttribute::NONE,
    )?;
    finish_prototype(scope, policy_prototype, policy_constructor)?;
    define_data(
        scope,
        global,
        "TrustedTypePolicy",
        policy_constructor.into(),
        v8::PropertyAttribute::DONT_ENUM,
    )?;

    let (factory_constructor, factory_prototype) =
        interface_constructor(scope, "TrustedTypePolicyFactory")?;
    let empty_html_getter = named_getter(scope, "emptyHTML", factory_empty_html)?;
    define_getter(scope, factory_prototype, "emptyHTML", empty_html_getter)?;
    let empty_script_getter = named_getter(scope, "emptyScript", factory_empty_script)?;
    define_getter(scope, factory_prototype, "emptyScript", empty_script_getter)?;
    let default_policy_getter = named_getter(scope, "defaultPolicy", factory_default_policy)?;
    define_getter(
        scope,
        factory_prototype,
        "defaultPolicy",
        default_policy_getter,
    )?;
    let create_policy = named_function(scope, "createPolicy", 1, factory_create_policy)?;
    define_data(
        scope,
        factory_prototype,
        "createPolicy",
        create_policy.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let get_attribute_type =
        named_function(scope, "getAttributeType", 2, factory_get_attribute_type)?;
    define_data(
        scope,
        factory_prototype,
        "getAttributeType",
        get_attribute_type.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let get_property_type = named_function(scope, "getPropertyType", 2, factory_get_property_type)?;
    define_data(
        scope,
        factory_prototype,
        "getPropertyType",
        get_property_type.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let get_type_mapping = named_function(scope, "getTypeMapping", 0, factory_get_type_mapping)?;
    define_data(
        scope,
        factory_prototype,
        "getTypeMapping",
        get_type_mapping.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let is_html = named_function(scope, "isHTML", 1, factory_is_html)?;
    define_data(
        scope,
        factory_prototype,
        "isHTML",
        is_html.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let is_script = named_function(scope, "isScript", 1, factory_is_script)?;
    define_data(
        scope,
        factory_prototype,
        "isScript",
        is_script.into(),
        v8::PropertyAttribute::NONE,
    )?;
    let is_script_url = named_function(scope, "isScriptURL", 1, factory_is_script_url)?;
    define_data(
        scope,
        factory_prototype,
        "isScriptURL",
        is_script_url.into(),
        v8::PropertyAttribute::NONE,
    )?;
    finish_prototype(scope, factory_prototype, factory_constructor)?;
    define_data(
        scope,
        global,
        "TrustedTypePolicyFactory",
        factory_constructor.into(),
        v8::PropertyAttribute::DONT_ENUM,
    )?;

    let factory = v8::Object::new(scope);
    if !factory
        .set_prototype(scope, factory_prototype.into())
        .unwrap_or(false)
        || !hidden_set(scope, factory, PROTOTYPE_POLICY, policy_prototype.into())
        || !hidden_set(scope, factory, PROTOTYPE_HTML, html_prototype.into())
        || !hidden_set(scope, factory, PROTOTYPE_SCRIPT, script_prototype.into())
        || !hidden_set(
            scope,
            factory,
            PROTOTYPE_SCRIPT_URL,
            script_url_prototype.into(),
        )
    {
        return Err(V8Error::NativeInstallation("trustedTypes"));
    }
    let empty = string(scope, "").ok_or(V8Error::SourceAllocation)?;
    let empty_html = trusted_value(scope, factory, TrustedKind::Html, empty)
        .ok_or(V8Error::NativeInstallation("trustedTypes.emptyHTML"))?;
    let empty = string(scope, "").ok_or(V8Error::SourceAllocation)?;
    let empty_script = trusted_value(scope, factory, TrustedKind::Script, empty)
        .ok_or(V8Error::NativeInstallation("trustedTypes.emptyScript"))?;
    if !hidden_set(scope, factory, EMPTY_HTML, empty_html.into())
        || !hidden_set(scope, factory, EMPTY_SCRIPT, empty_script.into())
    {
        return Err(V8Error::NativeInstallation("trustedTypes"));
    }
    let getter = v8::Function::builder(global_trusted_types)
        .data(factory.into())
        .length(0)
        .build(scope)
        .ok_or(V8Error::NativeInstallation("trustedTypes"))?;
    let getter_name = string(scope, "get trustedTypes").ok_or(V8Error::SourceAllocation)?;
    getter.set_name(getter_name);
    define_getter(scope, global, "trustedTypes", getter)
}
