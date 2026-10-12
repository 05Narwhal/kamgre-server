document.addEventListener('DOMContentLoaded', () => {

    // Get all "navbar-burger" elements
    const $navbarBurgers = Array.prototype.slice.call(document.querySelectorAll('.navbar-burger'), 0);

    // Add a click event on each of them
    $navbarBurgers.forEach(el => {
        el.addEventListener('click', () => {
            // Get the target from the "data-target" attribute
            const target = el.dataset.target;
            const $target = document.getElementById(target);

            // Toggle the "is-active" class on both the "navbar-burger" and the "navbar-menu"
            el.classList.toggle('is-active');
            $target.classList.toggle('is-active');

        });
    });

    // make bulma tabs work
    for (let $tab of document.querySelectorAll('.tabs li')) {
        $tab.addEventListener('click', function () {

            for (let $tab of document.querySelectorAll('.tabs li')) {
                $tab.classList.remove('is-active');
            }

            this.classList.add('is-active');

            for (let $tab of document.querySelectorAll('.tab-content.is-active')) {
                $tab.classList.remove('is-active');
            }
            document.getElementById(this.dataset.target).classList.add('is-active');
        });
    }
});